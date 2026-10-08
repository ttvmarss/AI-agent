# Zalius M0 - READ-ONLY Windows environment audit. Run on the owner's PC:
#   powershell -ExecutionPolicy Bypass -File scripts\audit_windows.ps1 > audit_windows.txt
# Makes no changes, installs nothing, sends nothing over the network.
$ErrorActionPreference = 'Continue'
function Try-Run($label, [scriptblock]$b) { "=== $label ==="; try { & $b 2>&1 | Out-String } catch { "ERROR: $_" } }

Try-Run 'OS'        { Get-CimInstance Win32_OperatingSystem | Select Caption,Version,BuildNumber,OSArchitecture | Format-List }
Try-Run 'CPU'       { Get-CimInstance Win32_Processor | Select Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | Format-List }
Try-Run 'RAM'       { Get-CimInstance Win32_ComputerSystem | Select @{n='TotalGB';e={[math]::Round($_.TotalPhysicalMemory/1GB,1)}} | Format-List }
Try-Run 'GPU (WMI)' { Get-CimInstance Win32_VideoController | Select Name,DriverVersion | Format-List }
Try-Run 'GPU (nvidia-smi)' { nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,compute_cap,temperature.gpu,power.limit --format=csv }
Try-Run 'Disks'     { Get-PSDrive -PSProvider FileSystem | Select Name,@{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}},@{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}} | Format-Table }
Try-Run 'Python'    { python --version; py -0p }
Try-Run 'PyTorch'   { python -c "import torch;print(torch.__version__, 'cuda', torch.version.cuda, 'avail', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda'); print(torch.cuda.get_device_capability(0) if torch.cuda.is_available() else '')" }
Try-Run '.NET'      { dotnet --list-sdks; dotnet --list-runtimes }
Try-Run 'Node'      { node --version; npm --version }
Try-Run 'Git'       { git --version }
Try-Run 'Hyper-V (VM testbench TB-003)' { Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All | Select FeatureName,State | Format-List }
Try-Run 'Virtualization firmware' { (Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled }
Try-Run 'Windows edition (Hyper-V needs Pro+)' { (Get-ComputerInfo).WindowsEditionId }
Try-Run 'Power plan' { powercfg /getactivescheme }
