Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

projectDir = FSO.GetParentFolderName(WScript.ScriptFullName)
weztermExe = "D:\Program Files\WezTerm\wezterm.exe"
userHome = WshShell.ExpandEnvironmentStrings("%USERPROFILE%")
socketDir = userHome & "\.local\share\wezterm"
tempDir = WshShell.ExpandEnvironmentStrings("%TEMP%")
Dim q : q = Chr(34)

' ==== 第1步：查找 WezTerm 的 socket ====
socketPath = ""
Set rx = New RegExp
rx.Pattern = "PID:\s+(\d+)"
rx.Global = True

outFile = tempDir & "\cl-out.txt"
WshShell.Run "cmd /c tasklist /FI " & q & "IMAGENAME eq wezterm-gui.exe" & q & " /FO LIST > " & q & outFile & q, 0, True

If FSO.FileExists(outFile) Then
    Set f = FSO.OpenTextFile(outFile, 1)
    If Not f.AtEndOfStream Then taskOut = f.ReadAll() Else taskOut = ""
    f.Close
    FSO.DeleteFile outFile
    Set ms = rx.Execute(taskOut)
    For i = 0 To ms.Count - 1
        c = socketDir & "\gui-sock-" & ms(i).SubMatches(0)
        If FSO.FileExists(c) Then socketPath = c : Exit For
    Next
End If

' ==== 第2步：WezTerm 没运行就启动它 ====
If socketPath = "" Then
    WshShell.Run q & weztermExe & q, 1, False
    For w = 1 To 20
        WScript.Sleep 500
        WshShell.Run "cmd /c tasklist /FI " & q & "IMAGENAME eq wezterm-gui.exe" & q & " /FO LIST > " & q & outFile & q, 0, True
        If FSO.FileExists(outFile) Then
            Set f2 = FSO.OpenTextFile(outFile, 1)
            If Not f2.AtEndOfStream Then t2 = f2.ReadAll() Else t2 = ""
            f2.Close
            FSO.DeleteFile outFile
            Set ms2 = rx.Execute(t2)
            For i = 0 To ms2.Count - 1
                c2 = socketDir & "\gui-sock-" & ms2(i).SubMatches(0)
                If FSO.FileExists(c2) Then socketPath = c2 : Exit For
            Next
        End If
        If socketPath <> "" Then Exit For
    Next
End If

If socketPath = "" Then WScript.Quit 1

' ==== 第3步：通过批处理文件在现有窗口开新标签 ====
bat = tempDir & "\cl.bat"
paneFile = tempDir & "\cl-pane.txt"

Set bf = FSO.CreateTextFile(bat, True)
bf.WriteLine "@echo off"
bf.WriteLine "set WEZTERM_UNIX_SOCKET=" & socketPath
bf.WriteLine q & weztermExe & q & " cli spawn --cwd " & q & projectDir & q & " > " & q & paneFile & q
bf.Close

WshShell.Run q & bat & q, 0, True

paneId = ""
If FSO.FileExists(paneFile) Then
    Set pf = FSO.OpenTextFile(paneFile, 1)
    If Not pf.AtEndOfStream Then paneId = Trim(pf.ReadAll()) Else paneId = ""
    pf.Close
    FSO.DeleteFile paneFile
End If
If FSO.FileExists(bat) Then FSO.DeleteFile bat
If paneId = "" Then WScript.Quit 1

' ==== 第4步：通过批处理发送 claude 命令 ====
WScript.Sleep 800

Set bf2 = FSO.CreateTextFile(bat, True)
bf2.WriteLine "@echo off"
bf2.WriteLine "set WEZTERM_UNIX_SOCKET=" & socketPath
bf2.WriteLine "echo claude --dangerously-skip-permissions| " & q & weztermExe & q & " cli send-text --pane-id " & paneId
bf2.Close

WshShell.Run q & bat & q, 0, True
If FSO.FileExists(bat) Then FSO.DeleteFile bat
