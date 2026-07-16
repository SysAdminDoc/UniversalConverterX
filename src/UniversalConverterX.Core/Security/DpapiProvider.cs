using System.Security.Cryptography;
using System.Text;

namespace UniversalConverterX.Core.Security;

/// <summary>
/// Windows DPAPI wrapper for at-rest encryption of sensitive configuration and credentials.
/// Data is protected for the current Windows user and bound to an application-specific entropy
/// value so unrelated callers cannot unprotect it accidentally.
/// </summary>
public static class DpapiProvider
{
    private const string EntropyPurpose = "UniversalConverterX.DPAPI.v2";
    private static readonly byte[] ApplicationEntropy =
        SHA256.HashData(Encoding.UTF8.GetBytes(EntropyPurpose));
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    /// <summary>
    /// Encrypt UTF-8 text using Windows DPAPI and the supplied optional entropy.
    /// </summary>
    public static DpapiResult<byte[]> Encrypt(string plaintext, byte[]? entropy = null)
    {
        ArgumentNullException.ThrowIfNull(plaintext);
        return Encrypt(Encoding.UTF8.GetBytes(plaintext), entropy);
    }

    /// <summary>
    /// Encrypt bytes using Windows DPAPI and the supplied optional entropy.
    /// </summary>
    public static DpapiResult<byte[]> Encrypt(byte[] plaintext, byte[]? entropy = null)
    {
        ArgumentNullException.ThrowIfNull(plaintext);

        if (!OperatingSystem.IsWindows())
        {
            return DpapiResult<byte[]>.Failure("Windows DPAPI is not available on this platform.");
        }

        try
        {
            var ciphertext = ProtectedData.Protect(
                plaintext,
                ResolveEntropy(entropy),
                DataProtectionScope.CurrentUser);
            return DpapiResult<byte[]>.SuccessResult(ciphertext);
        }
        catch (Exception ex) when (ex is CryptographicException or PlatformNotSupportedException)
        {
            return DpapiResult<byte[]>.Failure($"DPAPI encryption failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Decrypt DPAPI-protected bytes. When <paramref name="allowLegacyWithoutEntropy"/> is true,
    /// ciphertext created by the previous no-entropy implementation remains readable so callers
    /// can migrate it on their next successful write.
    /// </summary>
    public static DpapiResult<byte[]> Decrypt(
        byte[] ciphertext,
        byte[]? entropy = null,
        bool allowLegacyWithoutEntropy = true)
    {
        ArgumentNullException.ThrowIfNull(ciphertext);

        if (!OperatingSystem.IsWindows())
        {
            return DpapiResult<byte[]>.Failure("Windows DPAPI is not available on this platform.");
        }

        try
        {
            var plaintext = ProtectedData.Unprotect(
                ciphertext,
                ResolveEntropy(entropy),
                DataProtectionScope.CurrentUser);
            return DpapiResult<byte[]>.SuccessResult(plaintext);
        }
        catch (CryptographicException currentError) when (allowLegacyWithoutEntropy && entropy is null)
        {
            try
            {
                var plaintext = ProtectedData.Unprotect(
                    ciphertext,
                    optionalEntropy: null,
                    DataProtectionScope.CurrentUser);
                return DpapiResult<byte[]>.SuccessResult(plaintext, usedLegacyProtection: true);
            }
            catch (Exception legacyError) when (legacyError is CryptographicException or PlatformNotSupportedException)
            {
                return DpapiResult<byte[]>.Failure(
                    $"DPAPI decryption failed: {currentError.Message}; legacy retry failed: {legacyError.Message}");
            }
        }
        catch (Exception ex) when (ex is CryptographicException or PlatformNotSupportedException)
        {
            return DpapiResult<byte[]>.Failure($"DPAPI decryption failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Decrypt DPAPI-protected bytes and decode them as strict UTF-8.
    /// </summary>
    public static DpapiResult<string> DecryptString(
        byte[] ciphertext,
        byte[]? entropy = null,
        bool allowLegacyWithoutEntropy = true)
    {
        var result = Decrypt(ciphertext, entropy, allowLegacyWithoutEntropy);
        if (!result.Succeeded || result.Value is null)
        {
            return DpapiResult<string>.Failure(result.Error ?? "DPAPI decryption failed.");
        }

        try
        {
            return DpapiResult<string>.SuccessResult(
                StrictUtf8.GetString(result.Value),
                result.UsedLegacyProtection);
        }
        catch (DecoderFallbackException ex)
        {
            return DpapiResult<string>.Failure($"Decrypted data is not valid UTF-8: {ex.Message}");
        }
    }

    /// <summary>
    /// Return true if DPAPI is available on the current platform.
    /// </summary>
    public static bool IsAvailable() => OperatingSystem.IsWindows();

    private static byte[] ResolveEntropy(byte[]? entropy) => entropy ?? ApplicationEntropy;
}

/// <summary>
/// The outcome of a DPAPI operation. Failed operations never expose their input as output.
/// </summary>
public sealed record DpapiResult<T>(
    bool Succeeded,
    T? Value,
    string? Error,
    bool UsedLegacyProtection = false)
{
    internal static DpapiResult<T> SuccessResult(T value, bool usedLegacyProtection = false) =>
        new(true, value, null, usedLegacyProtection);

    internal static DpapiResult<T> Failure(string error) =>
        new(false, default, error);
}
