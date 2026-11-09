; Instalador de Herramientas PDF (se crea automáticamente en GitHub Actions)
[Setup]
AppName=Herramientas PDF
AppVersion=2.0
AppPublisher=Herramientas PDF
DefaultDirName={autopf}\Herramientas PDF
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=HerramientasPDF-Instalador
SetupIconFile=app\icon.ico
UninstallDisplayIcon={app}\HerramientasPDF.exe
Compression=lzma2/fast
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\HerramientasPDF\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Herramientas PDF"; Filename: "{app}\HerramientasPDF.exe"
Name: "{autodesktop}\Herramientas PDF"; Filename: "{app}\HerramientasPDF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HerramientasPDF.exe"; Description: "Abrir Herramientas PDF"; Flags: nowait postinstall skipifsilent
