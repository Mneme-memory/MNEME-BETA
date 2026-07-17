#include <windows.h>
#include <userenv.h>
#include <aclapi.h>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr wchar_t kProfileName[] = L"Mneme.ReadOnlyRunner";

struct LocalFreeDeleter {
    void operator()(void* value) const { if (value) LocalFree(value); }
};

template <typename T>
using local_ptr = std::unique_ptr<T, LocalFreeDeleter>;

std::wstring win_error(const wchar_t* action, DWORD code = GetLastError()) {
    wchar_t* message = nullptr;
    FormatMessageW(FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                       FORMAT_MESSAGE_IGNORE_INSERTS,
                   nullptr, code, 0, reinterpret_cast<wchar_t*>(&message), 0, nullptr);
    local_ptr<wchar_t> owned(message);
    return std::wstring(action) + L" failed (" + std::to_wstring(code) + L"): " +
           (message ? message : L"unknown error");
}

std::wstring quote_arg(const std::wstring& value) {
    std::wstring out = L"\"";
    size_t slashes = 0;
    for (wchar_t ch : value) {
        if (ch == L'\\') {
            ++slashes;
        } else if (ch == L'\"') {
            out.append(slashes * 2 + 1, L'\\');
            out.push_back(ch);
            slashes = 0;
        } else {
            out.append(slashes, L'\\');
            slashes = 0;
            out.push_back(ch);
        }
    }
    out.append(slashes * 2, L'\\');
    out.push_back(L'\"');
    return out;
}

// Writing an inheritable ACE propagates it across the whole tree, which costs
// seconds on large roots (the Python runtime, the profile directory). The
// container SID is stable across runs, so skip the write when a covering ACE
// is already present.
bool has_matching_ace(PACL acl, PSID sid, DWORD permissions, DWORD inheritance) {
    if (!acl) return false;
    GENERIC_MAPPING mapping{FILE_GENERIC_READ, FILE_GENERIC_WRITE,
                            FILE_GENERIC_EXECUTE, FILE_ALL_ACCESS};
    DWORD wanted = permissions;
    MapGenericMask(&wanted, &mapping);
    DWORD wanted_flags = inheritance & (CONTAINER_INHERIT_ACE | OBJECT_INHERIT_ACE);
    for (DWORD i = 0; i < acl->AceCount; ++i) {
        void* raw = nullptr;
        if (!GetAce(acl, i, &raw)) continue;
        auto* header = static_cast<ACE_HEADER*>(raw);
        if (header->AceType != ACCESS_ALLOWED_ACE_TYPE) continue;
        auto* ace = static_cast<ACCESS_ALLOWED_ACE*>(raw);
        if (!EqualSid(&ace->SidStart, sid)) continue;
        DWORD mask = ace->Mask;
        MapGenericMask(&mask, &mapping);
        if ((mask & wanted) != wanted) continue;
        if ((header->AceFlags & wanted_flags) != wanted_flags) continue;
        return true;
    }
    return false;
}

bool grant_path(const fs::path& path, PSID sid, DWORD permissions, DWORD inheritance,
                std::wstring& error) {
    PACL old_acl = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    DWORD status = GetNamedSecurityInfoW(
        path.c_str(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, &old_acl, nullptr, &descriptor);
    local_ptr<void> owned_descriptor(descriptor);
    if (status != ERROR_SUCCESS) {
        error = win_error(L"GetNamedSecurityInfo", status);
        return false;
    }
    if (has_matching_ace(old_acl, sid, permissions, inheritance)) {
        return true;
    }

    EXPLICIT_ACCESSW entry{};
    entry.grfAccessPermissions = permissions;
    entry.grfAccessMode = GRANT_ACCESS;
    entry.grfInheritance = inheritance;
    entry.Trustee.TrusteeForm = TRUSTEE_IS_SID;
    entry.Trustee.TrusteeType = TRUSTEE_IS_WELL_KNOWN_GROUP;
    entry.Trustee.ptstrName = static_cast<LPWSTR>(sid);

    PACL new_acl = nullptr;
    status = SetEntriesInAclW(1, &entry, old_acl, &new_acl);
    local_ptr<void> owned_acl(new_acl);
    if (status != ERROR_SUCCESS) {
        error = win_error(L"SetEntriesInAcl", status);
        return false;
    }
    status = SetNamedSecurityInfoW(
        const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
        nullptr, nullptr, new_acl, nullptr);
    if (status != ERROR_SUCCESS) {
        error = win_error(L"SetNamedSecurityInfo", status);
        return false;
    }
    return true;
}

bool grant_tree(const fs::path& root, PSID sid, DWORD permissions, std::wstring& error) {
    const DWORD inherit = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
    return grant_path(root, sid, permissions, inherit, error);
}

bool get_container_sid(PSID* sid, std::wstring& error) {
    HRESULT result = CreateAppContainerProfile(
        kProfileName, L"Mneme read-only Python runner",
        L"Isolated execution identity for Mneme @run", nullptr, 0, sid);
    if (result == HRESULT_FROM_WIN32(ERROR_ALREADY_EXISTS)) {
        result = DeriveAppContainerSidFromAppContainerName(kProfileName, sid);
    }
    if (FAILED(result)) {
        error = L"AppContainer profile setup failed (HRESULT " +
                std::to_wstring(static_cast<unsigned long>(result)) + L")";
        return false;
    }
    return true;
}

struct Options {
    fs::path python;
    fs::path script;
    fs::path input_root;
    fs::path scratch;
    fs::path stdout_path;
    fs::path stderr_path;
    fs::path container_home;
    fs::path container_temp;
    DWORD timeout_ms = 10000;
    SIZE_T memory_bytes = 256ULL * 1024ULL * 1024ULL;
    uintmax_t scratch_limit_bytes = 64ULL * 1024ULL * 1024ULL;
    std::map<std::wstring, std::wstring> environment;
    std::vector<fs::path> read_roots;
};

bool parse_options(int argc, wchar_t** argv, Options& out, std::wstring& error) {
    for (int i = 1; i < argc; ++i) {
        std::wstring key = argv[i];
        auto take = [&]() -> const wchar_t* {
            return (++i < argc) ? argv[i] : nullptr;
        };
        const wchar_t* value = nullptr;
        if (key == L"--python" && (value = take())) out.python = value;
        else if (key == L"--script" && (value = take())) out.script = value;
        else if (key == L"--input-root" && (value = take())) out.input_root = value;
        else if (key == L"--scratch" && (value = take())) out.scratch = value;
        else if (key == L"--stdout" && (value = take())) out.stdout_path = value;
        else if (key == L"--stderr" && (value = take())) out.stderr_path = value;
        else if (key == L"--timeout-ms" && (value = take())) out.timeout_ms = std::stoul(value);
        else if (key == L"--memory-mb" && (value = take()))
            out.memory_bytes = static_cast<SIZE_T>(std::stoull(value)) * 1024ULL * 1024ULL;
        else if (key == L"--scratch-mb" && (value = take()))
            out.scratch_limit_bytes = std::stoull(value) * 1024ULL * 1024ULL;
        else if (key == L"--read" && (value = take())) out.read_roots.emplace_back(value);
        else if (key == L"--env" && (value = take())) {
            std::wstring pair = value;
            size_t equals = pair.find(L'=');
            if (equals == std::wstring::npos || equals == 0) {
                error = L"Invalid --env value";
                return false;
            }
            out.environment[pair.substr(0, equals)] = pair.substr(equals + 1);
        } else {
            error = L"Unknown or incomplete argument: " + key;
            return false;
        }
    }
    if (out.python.empty() || out.script.empty() || out.input_root.empty() ||
        out.scratch.empty() || out.stdout_path.empty() || out.stderr_path.empty()) {
        error = L"Missing required arguments";
        return false;
    }
    return true;
}

std::vector<wchar_t> make_environment(const Options& options) {
    wchar_t system_root_buffer[MAX_PATH]{};
    DWORD system_root_length = GetEnvironmentVariableW(
        L"SYSTEMROOT", system_root_buffer, static_cast<DWORD>(std::size(system_root_buffer)));
    std::wstring system_root = system_root_length ? system_root_buffer : L"C:\\Windows";
    std::wstring sandbox_home = options.container_home.wstring();
    std::wstring sandbox_temp = options.container_temp.wstring();
    std::wstring home_root = options.container_home.root_name().wstring();
    std::wstring home_relative = options.container_home.lexically_relative(
        options.container_home.root_path()).wstring();
    std::map<std::wstring, std::wstring> values = {
        {L"APPDATA", sandbox_home},
        {L"COMSPEC", fs::path(system_root).append(L"System32\\cmd.exe").wstring()},
        {L"PYTHONHOME", options.python.parent_path().wstring()},
        {L"PYTHONNOUSERSITE", L"1"},
        {L"PYTHONDONTWRITEBYTECODE", L"1"},
        {L"PYTHONIOENCODING", L"utf-8"},
        {L"HOME", sandbox_home},
        {L"HOMEDRIVE", home_root},
        {L"HOMEPATH", L"\\" + home_relative},
        {L"LOCALAPPDATA", sandbox_home},
        {L"SYSTEMROOT", system_root},
        {L"PATH", options.python.parent_path().wstring() + L";" +
                      fs::path(system_root).append(L"System32").wstring()},
        {L"TEMP", sandbox_temp},
        {L"TMP", sandbox_temp},
        {L"USERPROFILE", sandbox_home},
        {L"WINDIR", system_root},
    };
    values.insert(options.environment.begin(), options.environment.end());
    std::vector<wchar_t> block;
    for (const auto& [key, value] : values) {
        std::wstring item = key + L"=" + value;
        block.insert(block.end(), item.begin(), item.end());
        block.push_back(L'\0');
    }
    block.push_back(L'\0');
    return block;
}

bool create_capture_pipe(HANDLE* read_handle, HANDLE* write_handle) {
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    if (!CreatePipe(read_handle, write_handle, &attributes, 0)) return false;
    return SetHandleInformation(*read_handle, HANDLE_FLAG_INHERIT, 0) != FALSE;
}

HANDLE open_null_input() {
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    return CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                       &attributes, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
}

void drain_pipe(HANDLE read_handle, std::string* output, size_t limit) {
    char buffer[4096];
    DWORD read = 0;
    while (ReadFile(read_handle, buffer, sizeof(buffer), &read, nullptr) && read > 0) {
        if (output->size() < limit) {
            size_t remaining = limit - output->size();
            output->append(buffer, std::min<size_t>(read, remaining));
        }
    }
}

bool write_capture(const fs::path& path, const std::string& content) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output.write(content.data(), static_cast<std::streamsize>(content.size()));
    return output.good();
}

uintmax_t directory_size(const fs::path& path) {
    uintmax_t total = 0;
    std::error_code error;
    fs::recursive_directory_iterator iterator(
        path, fs::directory_options::skip_permission_denied, error);
    fs::recursive_directory_iterator end;
    while (!error && iterator != end) {
        if (iterator->is_regular_file(error)) {
            total += iterator->file_size(error);
        }
        iterator.increment(error);
    }
    return total;
}

bool purge_container_storage(const fs::path& home, std::wstring& error) {
    std::error_code operation_error;
    if (fs::exists(home, operation_error)) {
        for (const auto& entry : fs::directory_iterator(home, operation_error)) {
            fs::remove_all(entry.path(), operation_error);
            if (operation_error) break;
        }
    }
    if (operation_error) {
        std::string message = operation_error.message();
        error = L"Unable to clear AppContainer storage: " +
                std::wstring(message.begin(), message.end());
        return false;
    }
    fs::create_directories(home / L"AC" / L"Temp", operation_error);
    if (operation_error) {
        std::string message = operation_error.message();
        error = L"Unable to prepare AppContainer storage: " +
                std::wstring(message.begin(), message.end());
        return false;
    }
    return true;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    Options options;
    std::wstring error;
    try {
        if (!parse_options(argc, argv, options, error)) {
            std::wcerr << error << L"\n";
            return 202;
        }
    } catch (const std::exception& exc) {
        std::cerr << "Invalid numeric argument: " << exc.what() << "\n";
        return 202;
    }

    for (const auto& path : {options.python, options.script, options.input_root}) {
        if (!fs::exists(path)) {
            std::wcerr << L"Required path does not exist: " << path << L"\n";
            return 202;
        }
    }
    fs::create_directories(options.scratch);

    PSID raw_sid = nullptr;
    if (!get_container_sid(&raw_sid, error)) {
        std::wcerr << error << L"\n";
        return 203;
    }
    local_ptr<void> sid(raw_sid);

    wchar_t local_app_data[MAX_PATH]{};
    DWORD local_length = GetEnvironmentVariableW(
        L"LOCALAPPDATA", local_app_data, static_cast<DWORD>(std::size(local_app_data)));
    if (!local_length) {
        std::wcerr << L"LOCALAPPDATA is unavailable\n";
        return 203;
    }
    options.container_home = fs::path(local_app_data) / L"Packages" /
                             L"mneme.readonlyrunner";
    options.container_temp = options.container_home / L"AC" / L"Temp";
    if (!purge_container_storage(options.container_home, error)) {
        std::wcerr << error << L"\n";
        return 207;
    }

    const DWORD inherit = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
    bool policy_ok = true;
    policy_ok = policy_ok && grant_path(options.python.parent_path(), raw_sid,
                                        GENERIC_READ | GENERIC_EXECUTE, inherit, error);
    policy_ok = policy_ok && grant_tree(options.input_root, raw_sid,
                                        GENERIC_READ | GENERIC_EXECUTE, error);
    for (const auto& read_root : options.read_roots) {
        if (!fs::exists(read_root)) continue;
        policy_ok = policy_ok && grant_tree(read_root, raw_sid,
                                            GENERIC_READ | GENERIC_EXECUTE, error);
    }
    policy_ok = policy_ok && grant_path(options.scratch, raw_sid, GENERIC_ALL, inherit, error);
    if (!policy_ok) {
        std::wcerr << error << L"\n";
        return 204;
    }

    HANDLE stdout_read = nullptr;
    HANDLE stdout_handle = nullptr;
    HANDLE stderr_read = nullptr;
    HANDLE stderr_handle = nullptr;
    HANDLE stdin_handle = open_null_input();
    if (!create_capture_pipe(&stdout_read, &stdout_handle) ||
        !create_capture_pipe(&stderr_read, &stderr_handle) ||
        stdin_handle == INVALID_HANDLE_VALUE) {
        std::wcerr << win_error(L"Opening standard handles") << L"\n";
        return 205;
    }

    SECURITY_CAPABILITIES capabilities{};
    capabilities.AppContainerSid = raw_sid;

    SIZE_T attribute_size = 0;
    InitializeProcThreadAttributeList(nullptr, 2, 0, &attribute_size);
    std::vector<unsigned char> attribute_storage(attribute_size);
    auto* attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attribute_storage.data());
    if (!InitializeProcThreadAttributeList(attributes, 2, 0, &attribute_size)) {
        std::wcerr << win_error(L"InitializeProcThreadAttributeList") << L"\n";
        return 205;
    }
    HANDLE inherited_handles[] = {stdin_handle, stdout_handle, stderr_handle};
    bool attributes_ok =
        UpdateProcThreadAttribute(
            attributes, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            &capabilities, sizeof(capabilities), nullptr, nullptr) &&
        UpdateProcThreadAttribute(
            attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            inherited_handles, sizeof(inherited_handles), nullptr, nullptr);
    if (!attributes_ok) {
        std::wcerr << win_error(L"UpdateProcThreadAttribute") << L"\n";
        DeleteProcThreadAttributeList(attributes);
        return 205;
    }

    HANDLE job = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags =
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
        JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    limits.BasicLimitInformation.ActiveProcessLimit = 1;
    limits.ProcessMemoryLimit = options.memory_bytes;
    if (!job || !SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                         &limits, sizeof(limits))) {
        std::wcerr << win_error(L"Configuring job object") << L"\n";
        DeleteProcThreadAttributeList(attributes);
        return 205;
    }

    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdOutput = stdout_handle;
    startup.StartupInfo.hStdError = stderr_handle;
    startup.StartupInfo.hStdInput = stdin_handle;
    startup.lpAttributeList = attributes;

    std::wstring command = quote_arg(options.python.wstring()) + L" -I " +
                           quote_arg(options.script.wstring());
    std::vector<wchar_t> command_buffer(command.begin(), command.end());
    command_buffer.push_back(L'\0');
    auto environment = make_environment(options);
    PROCESS_INFORMATION process{};
    DWORD flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_NO_WINDOW |
                  CREATE_UNICODE_ENVIRONMENT;
    BOOL created = CreateProcessW(
        options.python.c_str(), command_buffer.data(), nullptr, nullptr, TRUE, flags,
        environment.data(), options.scratch.c_str(), &startup.StartupInfo, &process);
    DeleteProcThreadAttributeList(attributes);
    if (!created) {
        std::wcerr << win_error(L"CreateProcess") << L"\n";
        CloseHandle(job);
        CloseHandle(stdout_handle);
        CloseHandle(stderr_handle);
        CloseHandle(stdin_handle);
        return 206;
    }
    if (!AssignProcessToJobObject(job, process.hProcess)) {
        std::wcerr << win_error(L"AssignProcessToJobObject") << L"\n";
        TerminateProcess(process.hProcess, 1);
        return 206;
    }
    std::string captured_stdout;
    std::string captured_stderr;
    constexpr size_t kCaptureLimit = 64 * 1024;
    std::thread stdout_thread(drain_pipe, stdout_read, &captured_stdout, kCaptureLimit);
    std::thread stderr_thread(drain_pipe, stderr_read, &captured_stderr, kCaptureLimit);
    CloseHandle(stdout_handle);
    CloseHandle(stderr_handle);
    ResumeThread(process.hThread);
    ULONGLONG deadline = GetTickCount64() + options.timeout_ms;
    DWORD wait_result = WAIT_TIMEOUT;
    bool scratch_limit_exceeded = false;
    while (true) {
        ULONGLONG now = GetTickCount64();
        if (now >= deadline) break;
        DWORD remaining = static_cast<DWORD>(std::min<ULONGLONG>(deadline - now, 250));
        wait_result = WaitForSingleObject(process.hProcess, remaining);
        if (wait_result == WAIT_OBJECT_0 || wait_result == WAIT_FAILED) break;
        uintmax_t used = directory_size(options.scratch) +
                         directory_size(options.container_home);
        if (used > options.scratch_limit_bytes) {
            scratch_limit_exceeded = true;
            break;
        }
    }
    if (wait_result != WAIT_OBJECT_0) {
        DWORD termination_code = scratch_limit_exceeded ? 125 : 124;
        if (wait_result == WAIT_FAILED) {
            std::wcerr << win_error(L"Waiting for sandbox process") << L"\n";
            termination_code = 1;
        }
        TerminateJobObject(job, termination_code);
        WaitForSingleObject(process.hProcess, 2000);
    }
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);

    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    CloseHandle(job);
    CloseHandle(stdin_handle);
    stdout_thread.join();
    stderr_thread.join();
    CloseHandle(stdout_read);
    CloseHandle(stderr_read);
    if (scratch_limit_exceeded) {
        captured_stderr += "\n[sandbox] Disposable storage limit exceeded.";
    }
    if (!write_capture(options.stdout_path, captured_stdout) ||
        !write_capture(options.stderr_path, captured_stderr)) {
        std::wcerr << L"Writing captured output failed\n";
        return 205;
    }
    if (!purge_container_storage(options.container_home, error)) {
        std::wcerr << error << L"\n";
        return 207;
    }
    if (wait_result == WAIT_FAILED) return 205;
    if (scratch_limit_exceeded) return 125;
    return wait_result == WAIT_TIMEOUT ? 124 : static_cast<int>(exit_code);
}
