cmake_minimum_required(VERSION 3.20)
project(mneme_runner LANGUAGES CXX)

add_executable(mneme-runner runner.cpp)
target_compile_features(mneme-runner PRIVATE cxx_std_17)
target_compile_definitions(mneme-runner PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(mneme-runner PRIVATE advapi32 userenv)

if(MSVC)
  target_compile_options(mneme-runner PRIVATE /W4 /WX /permissive-)
  set_property(TARGET mneme-runner PROPERTY
    MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
