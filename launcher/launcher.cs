// Signal Pipeline launcher: a tiny native Windows starter with the football icon,
// in the same spirit as the original tool's launcher.
//
// Build (from this folder):
//   build.bat
// or by hand:
//   %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe /nologo /target:winexe
//       /win32icon:..\src\signal_pipeline\ui\assets\icon.ico /out:"..\Signal Pipeline.exe" launcher.cs
//
// Its only job: start the dashboard from its own folder, without a console window, using
// the project's virtual environment (.venv) if there is one, else pythonw from PATH. Source
// changes take effect immediately, no rebuild needed. On failure it says what to check.
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

class SignalPipelineLauncher
{
    [STAThread]
    static void Main()
    {
        string dir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string venv = Path.Combine(dir, ".venv", "Scripts", "pythonw.exe");
        var psi = new ProcessStartInfo
        {
            FileName = File.Exists(venv) ? venv : "pythonw.exe",  // GUI mode: no console window
            Arguments = "-m signal_pipeline ui",
            WorkingDirectory = dir,                                 // data\ and .env are found here
            UseShellExecute = false,
        };
        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Nem sikerült elindítani a Signal Pipeline-t.\n\n" +
                "Van .venv a mappában, vagy Python a PATH-on? Telepítés:\n" +
                "  python -m venv .venv\n" +
                "  .venv\\Scripts\\pip install -e \".[ui,remote]\"\n\n" +
                "Hiba: " + ex.Message,
                "Signal Pipeline", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
