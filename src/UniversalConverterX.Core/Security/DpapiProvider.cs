using System.Security.Cryptography;
using System.Text;

namespace UniversalConverterX.Core.Security;

/// <summary>
/// Windows DPAPI wrapper for at-rest encryption of sensitive configuration and credentials.
/// Encrypts to LocalMachine scope, making the encrypted blob decryptable by any user on the
/// same Windows install.
///
/// Non-Windows platforms (macOS, Linux) return plaintext (no-op graceful degradation).
/// </summary>
public static class DpapiProvider
{
    /// <summary>
    /// Encrypt plaintext bytes using Windows DPAPI (LocalMachine scope).
    /// </summary>
    /// <param name="plaintext">UTF-8 text to encrypt.</param>
    /// <returns>Encrypted bytes (safe for at-rest storage on Windows).</returns>
    public static byte[] Encrypt(string plaintext)
    {
        if (string.IsNullOrEmpty(plaintext))
            return [];

        var bytes = Encoding.UTF8.GetBytes(plaintext);
        return Encrypt(bytes);
    }

    /// <summary>
    /// Encrypt raw bytes using Windows DPAPI (LocalMachine scope).
    /// </summary>
    /// <param name="plaintext">Bytes to encrypt.</param>
    /// <returns>Encrypted bytes (safe for at-rest storage on Windows).</returns>
    public static byte[] Encrypt(byte[] plaintext)
    {
        if (!IsAvailable())
            return plaintext; // Graceful no-op on non-Windows

        try
        {
#if WINDOWS
            return System.Security.Cryptography.ProtectedData.Protect(
                plaintext, null, System.Security.Cryptography.DataProtectionScope.LocalMachine);
#else
            return plaintext;
#endif
        }
        catch (Exception ex)
        {
            // DPAPI failure (GPO restrictions, re-imaged host) — fall back to plaintext
            // rather than crash. Sidecar logs this; C# side is best-effort.
            System.Diagnostics.Debug.WriteLine($"DPAPI encryption failed: {ex.Message}");
            return plaintext;
        }
    }

    /// <summary>
    /// Decrypt DPAPI-protected bytes (LocalMachine scope).
    /// </summary>
    /// <param name="ciphertext">Encrypted bytes (from <see cref="Encrypt(byte[])"/>).</param>
    /// <returns>Original plaintext bytes.</returns>
    public static byte[] Decrypt(byte[] ciphertext)
    {
        if (!IsAvailable())
            return ciphertext; // Graceful no-op on non-Windows

        try
        {
#if WINDOWS
            return System.Security.Cryptography.ProtectedData.Unprotect(
                ciphertext, null, System.Security.Cryptography.DataProtectionScope.LocalMachine);
#else
            return ciphertext;
#endif
        }
        catch (Exception ex)
        {
            // DPAPI failure (blob corrupted, encrypted on different machine, re-imaged host) —
            // treat as unencrypted and return as-is. Best-effort graceful degradation.
            System.Diagnostics.Debug.WriteLine($"DPAPI decryption failed: {ex.Message}");
            return ciphertext;
        }
    }

    /// <summary>
    /// Decrypt DPAPI-protected bytes and decode as UTF-8 string.
    /// </summary>
    /// <param name="ciphertext">Encrypted bytes.</param>
    /// <returns>Decrypted string, or empty if decryption fails.</returns>
    public static string DecryptString(byte[] ciphertext)
    {
        try
        {
            var plaintext = Decrypt(ciphertext);
            return Encoding.UTF8.GetString(plaintext);
        }
        catch
        {
            return string.Empty;
        }
    }

    /// <summary>
    /// Return True if DPAPI is available on the current platform (Windows only).
    /// </summary>
    public static bool IsAvailable()
    {
        return OperatingSystem.IsWindows();
    }
}
