using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Manager.Core;

/// <summary>The access code, kept in Windows Credential Manager and nowhere else.</summary>
public static class CredentialStore
{
    private const string Target = "ShabbatDisplayManager";
    private const uint CredTypeGeneric = 1;
    private const uint CredPersistLocalMachine = 2;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Credential
    {
        public uint Flags;
        public uint Type;
        public string TargetName;
        public string? Comment;
        public FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public string? TargetAlias;
        public string? UserName;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredReadW(string target, uint type, uint flags, out IntPtr credential);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredWriteW(ref Credential credential, uint flags);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredDeleteW(string target, uint type, uint flags);

    [DllImport("advapi32.dll")]
    private static extern void CredFree(IntPtr buffer);

    public static string? Read()
    {
        if (!CredReadW(Target, CredTypeGeneric, 0, out var p)) return null;
        try
        {
            var c = Marshal.PtrToStructure<Credential>(p);
            return c.CredentialBlobSize == 0 ? null : Marshal.PtrToStringUni(c.CredentialBlob, (int)c.CredentialBlobSize / 2);
        }
        finally
        {
            CredFree(p);
        }
    }

    public static void Write(string key)
    {
        var blob = Marshal.StringToCoTaskMemUni(key);
        try
        {
            var c = new Credential
            {
                Type = CredTypeGeneric,
                TargetName = Target,
                CredentialBlobSize = (uint)(key.Length * 2),
                CredentialBlob = blob,
                Persist = CredPersistLocalMachine,
                UserName = Environment.UserName,
            };
            if (!CredWriteW(ref c, 0))
                throw new InvalidOperationException("Windows couldn't save the access code (error " + Marshal.GetLastWin32Error() + ").");
        }
        finally
        {
            Marshal.ZeroFreeCoTaskMemUnicode(blob);
        }
    }

    public static void Delete() => CredDeleteW(Target, CredTypeGeneric, 0);
}
