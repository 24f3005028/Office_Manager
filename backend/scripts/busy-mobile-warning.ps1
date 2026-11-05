$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
if (![Environment]::UserInteractive) { exit 3 }
# A locked desktop cannot display the warning to the person using the computer.
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class OfficeDesktop {
  [DllImport("user32.dll", SetLastError=true)] public static extern IntPtr OpenInputDesktop(uint f, bool i, uint a);
  [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr d);
  [DllImport("user32.dll")] public static extern bool SwitchDesktop(IntPtr d);
}
'@
$desktop = [OfficeDesktop]::OpenInputDesktop(0, $false, 0x0100)
if ($desktop -eq [IntPtr]::Zero) { exit 3 }
try { if (![OfficeDesktop]::SwitchDesktop($desktop)) { exit 3 } }
finally { [void][OfficeDesktop]::CloseDesktop($desktop) }
$script:allowed = $false
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Office mobile request - is anyone using BUSY?'
$form.Size = New-Object System.Drawing.Size(590, 270)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.Font = New-Object System.Drawing.Font('Segoe UI', 11)
$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(22, 20)
$label.Size = New-Object System.Drawing.Size(540, 105)
$label.Text = "A mobile user needs an outstanding report from BUSY.`r`n`r`nStarting in 5 seconds. If you are working in BUSY, cancel this request to keep your work uninterrupted."
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = "I'm using BUSY - cancel"
$cancel.Location = New-Object System.Drawing.Point(22, 150)
$cancel.Size = New-Object System.Drawing.Size(285, 48)
$cancel.Add_Click({ $script:allowed = $false; $form.Close() })
$continue = New-Object System.Windows.Forms.Button
$continue.Text = 'Ignore and continue now'
$continue.Location = New-Object System.Drawing.Point(320, 150)
$continue.Size = New-Object System.Drawing.Size(240, 48)
$continue.Add_Click({ $script:allowed = $true; $form.Close() })
$form.Controls.AddRange(@($label, $cancel, $continue))
$form.CancelButton = $cancel
# Enter also cancels: accidental typing never confirms an immediate takeover.
$form.AcceptButton = $cancel
$clock = New-Object System.Diagnostics.Stopwatch
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 100
$timer.Add_Tick({
    $remaining = [Math]::Max(0, 5 - [Math]::Floor($clock.Elapsed.TotalSeconds))
    $form.Text = "Office mobile request - BUSY starts in $remaining seconds"
    if ($clock.Elapsed.TotalSeconds -ge 5) {
        $script:allowed = $true
        $form.Close()
    }
})
$form.Add_Shown({ $cancel.Focus(); $clock.Start(); $timer.Start() })
$form.Add_FormClosing({ $timer.Stop() })
[void]$form.ShowDialog()
$timer.Dispose()
$form.Dispose()
if ($script:allowed) { exit 0 }
exit 2
