; Inno Setup script for SheinExtract.
; Compile with:  iscc installer.iss
; Produces: dist\SheinExtract-Setup-{version}.exe

#define MyAppName "SHEIN 上架工具"
#define MyAppNameAscii "SheinExtract"
#define MyAppVersion "3.6.0"          ; Keep in sync with version.py
#define MyAppPublisher "MikeLiu93"
#define MyAppURL "https://github.com/MikeLiu93/shein-extract"
#define MyAppExeName "SheinExtract.exe"

[Setup]
; AppId is a unique GUID identifying this app — do NOT change between versions.
AppId={{B47DA8E2-9F61-4E91-8C3C-3A26A9F25F11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases

; Install per-user (no admin elevation needed) — friendlier for office laptops.
DefaultDirName={localappdata}\{#MyAppNameAscii}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

; Output
OutputDir=dist
OutputBaseFilename=SheinExtract-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Allow upgrade install over an existing version
UsePreviousAppDir=yes
UsePreviousGroup=yes

; Languages
ShowLanguageDialog=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Default.isl"
; If ChineseSimplified.isl is missing in your Inno Setup install, change to "Default.isl".

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked
Name: "startmenuicon"; Description: "在开始菜单创建快捷方式"; GroupDescription: "附加任务:"

[Files]
; The PyInstaller-built .exe is the only binary we ship.
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Convenience launcher for the merge tool. Both .exe and the original .py
; would need to coexist for that to make sense — for now, the merge tool
; is reachable via Start menu shortcut that runs SheinExtract.exe with --merge.
; Skip until we wire that switch in app_main.py.

; License / docs (optional)
; Source: "INSTALL_GUIDE_CN.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenuicon
Name: "{group}\配置 {#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--config"; Tasks: startmenuicon
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userdesktop}\配置 {#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--config"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Mike's Q7: do NOT delete user config or Chrome profile on uninstall.
; The two preserved trees are:
;   %APPDATA%\shein-extract\          (config.env, last_update_check.json)
;   %USERPROFILE%\shein-cdp-profile\  (SHEIN login cookies)
; Nothing to add here — only files we explicitly drop in {app} get cleaned.
