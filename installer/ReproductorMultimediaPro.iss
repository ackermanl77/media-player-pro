; Instalador por usuario (sin permisos de administrador) de la carpeta onedir
; que genera ReproductorMultimediaPro.spec. Compilar con Inno Setup 6:
;   iscc /DAppVersion=0.1.0 installer\ReproductorMultimediaPro.iss
; (el workflow de build lo hace en windows-latest, donde iscc ya viene).
;
; Asociaciones de archivo: se registran como "capacidades" (Abrir con /
; Aplicaciones predeterminadas de Windows) sin adueñarse de ninguna
; extensión. Verbo extra "Agregar a la lista" (--enqueue): con una ventana ya
; abierta, la agrega a esa lista (player/single_instance.py).

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#define AppName "Reproductor Multimedia Pro"
#define AppExe "ReproductorMultimediaPro.exe"
#define AppKey "ReproductorMultimediaPro"

[Setup]
AppId={{6F1B7A52-3E0C-4C55-9A87-2B6E4E0B5D11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=MELEJ
DefaultDirName={localappdata}\Programs\{#AppKey}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=ReproductorMultimediaPro-{#AppVersion}-setup
; packaging/sign_and_package.py pasa /DSign y la herramienta "codesign":
; Inno Setup firma este instalador y el desinstalador que escribe.
#ifdef Sign
SignTool=codesign
SignedUninstaller=yes
#endif
SetupIconFile=..\player\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\dist\ReproductorMultimediaPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Aplicacion registrada (aparece en "Abrir con" y en Aplicaciones predeterminadas).
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\enqueue"; ValueType: string; ValueData: "Agregar a la lista de {#AppName}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\enqueue\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" --enqueue ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Media"; ValueType: string; ValueData: "Archivo multimedia"; Flags: uninsdeletekey
; Iconos de documento (8.7): grupos 1 y 2 del .exe (packaging/document_icons.py).
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Media\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},1"
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Media\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Media\shell\enqueue"; ValueType: string; ValueData: "Agregar a la lista de {#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Media\shell\enqueue\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" --enqueue ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Playlist"; ValueType: string; ValueData: "Lista de reproducción"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Playlist\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},2"
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Playlist\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Playlist\shell\enqueue"; ValueType: string; ValueData: "Agregar a la lista de {#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#AppKey}.Playlist\shell\enqueue\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" --enqueue ""%1"""
; Clave padre de Capabilities: sin esto quedaba vacia tras desinstalar.
Root: HKCU; Subkey: "Software\{#AppKey}"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\{#AppKey}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#AppKey}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Reproductor de música y video basado en libVLC"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\{#AppKey}\Capabilities"; Flags: uninsdeletevalue
; ProgId: "Media" (archivos multimedia) o "Playlist" (listas, con su propio icono).
#define Ext(str e, str ProgId = "Media") \
  'Root: HKCU; Subkey: "Software\' + AppKey + '\Capabilities\FileAssociations"; ValueType: string; ValueName: "' + e + '"; ValueData: "' + AppKey + '.' + ProgId + '"' + NewLine + \
  'Root: HKCU; Subkey: "Software\Classes\' + e + '\OpenWithProgids"; ValueType: string; ValueName: "' + AppKey + '.' + ProgId + '"; ValueData: ""; Flags: uninsdeletevalue' + NewLine + \
  'Root: HKCU; Subkey: "Software\Classes\Applications\' + AppExe + '\SupportedTypes"; ValueType: string; ValueName: "' + e + '"; ValueData: ""'
#emit Ext(".mp3")
#emit Ext(".flac")
#emit Ext(".wav")
#emit Ext(".m4a")
#emit Ext(".ogg")
#emit Ext(".opus")
#emit Ext(".aac")
#emit Ext(".wma")
#emit Ext(".mp4")
#emit Ext(".mkv")
#emit Ext(".avi")
#emit Ext(".mov")
#emit Ext(".wmv")
#emit Ext(".webm")
#emit Ext(".m4v")
#emit Ext(".ts")
#emit Ext(".m2ts")
#emit Ext(".mpg")
#emit Ext(".m3u", "Playlist")
#emit Ext(".m3u8", "Playlist")

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent
