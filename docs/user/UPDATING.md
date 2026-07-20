# Updating Mneme

*One-click updates are on the way. Until then, updating takes a few minutes—and Mneme now has a built-in importer for bringing an older install forward safely.*

---

## First, check where your data lives

Mneme v15.1 and later keep personal data outside the replaceable app folder, in:

```text
%LOCALAPPDATA%\Mneme
```

That home contains your `config.json`, every profile under `data`, and the global `system_instructions.txt`. If that folder already contains your Mneme data, use the short update path below.

Older versions kept those files inside the Mneme app folder. If your old Mneme folder contains `config.json` and `data`, use **Upgrading from v15.0.1 or earlier**. You no longer need to copy those files by hand.

> You cannot currently update with **Pull** in GitHub Desktop or `git pull`. Production releases use clean snapshots without shared history. Download the release ZIP instead.

---

## Updating v15.1 or later

If `%LOCALAPPDATA%\Mneme` already holds your data:

1. **Quit Mneme.** Right-click its tray icon and choose **Exit**.
2. **Download and extract** the latest `Mneme-release.zip` from the [Releases page](https://github.com/Mneme-memory/MNEME-BETA/releases/latest).
3. Put the new `Mneme` app folder somewhere permanent. You may replace the old app folder because your personal data is no longer inside it.
4. Run **`Mneme-Setup.exe`** from inside the new folder. This refreshes dependencies and shortcuts.
5. Launch Mneme and confirm your profiles and recent conversations appear.

Do not copy `data` or `config.json` into the new folder. Mneme finds them automatically in `%LOCALAPPDATA%\Mneme`.

---

## Upgrading from v15.0.1 or earlier

The recommended path is the setup wizard's verified importer. Your old install stays untouched as a rollback copy.

1. **Quit the old Mneme first.** Right-click its tray icon and choose **Exit**. Leave the old folder exactly where it is.
2. **Download and extract** the latest `Mneme-release.zip` into a separate, fresh folder. Do not extract it over the old install.
3. Run **`Mneme-Setup.exe`** inside the new folder.
4. Launch Mneme from the new shortcut or the new folder's **Launch Mneme** shortcut.
5. In the setup wizard, choose:

   **Let's get started → Import from a previous Mneme**

6. Select the old install if Mneme finds it automatically. If it does not appear, paste the path to the old Mneme folder—the folder containing `config.json` and `data`—and choose **Check**.
7. Review the profiles and message counts, then choose **Import**.
8. When Mneme opens, check your profile list, recent conversations, attachments, and any custom system instructions.

The importer copies your settings, API keys, profiles, memories, attachments, artifacts, and system instructions into `%LOCALAPPDATA%\Mneme`. Live SQLite databases are copied through a consistent snapshot, every copied database is integrity-checked, and the old install is never deleted or modified.

Once you are satisfied that the new version is working, you may delete the old app folder—or keep it for a while as an extra backup.

---

## If something looks off

- **The old install is still your safety net.** Launch it again if you need to return to the previous version.
- **The importer cannot find the old install:** paste the old folder's full path into the wizard. Select the Mneme folder itself, not an individual `memory.db` file.
- **The importer says the destination already contains data:** do not overwrite it. Keep both copies and ask for help identifying which Mneme home is current.
- **A profile or message count looks wrong before import:** stop there. The confirmation screen has not copied anything yet.
- **The setup wizard does not appear:** Mneme has already found a `config.json`, usually in `%LOCALAPPDATA%\Mneme` or in the new app folder. Do not delete either copy until you know which one contains your current data.

Still stuck? Download [GIVE-TO-CLAUDE-FOR-HELP.pdf](https://github.com/Mneme-memory/MNEME-BETA/releases/latest/download/GIVE-TO-CLAUDE-FOR-HELP.pdf), give it to Claude, and describe what happened.
