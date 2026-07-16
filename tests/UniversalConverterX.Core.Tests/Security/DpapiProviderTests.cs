using System.Security.Cryptography;
using System.Text;
using FluentAssertions;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Security;

public sealed class DpapiProviderTests
{
    [Fact]
    public void EncryptAndDecrypt_RoundTripWithDefaultEntropy()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var encrypted = DpapiProvider.Encrypt("credential-value");

        encrypted.Succeeded.Should().BeTrue(encrypted.Error);
        encrypted.Value.Should().NotBeNull();
        Encoding.UTF8.GetString(encrypted.Value!).Should().NotBe("credential-value");

        var decrypted = DpapiProvider.DecryptString(encrypted.Value!);

        decrypted.Succeeded.Should().BeTrue(decrypted.Error);
        decrypted.Value.Should().Be("credential-value");
        decrypted.UsedLegacyProtection.Should().BeFalse();
    }

    [Fact]
    public void Decrypt_WithDifferentEntropy_FailsWithoutReturningCiphertext()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var encrypted = DpapiProvider.Encrypt(
            "credential-value",
            Encoding.UTF8.GetBytes("purpose-one"));
        encrypted.Succeeded.Should().BeTrue(encrypted.Error);

        var decrypted = DpapiProvider.Decrypt(
            encrypted.Value!,
            Encoding.UTF8.GetBytes("purpose-two"));

        decrypted.Succeeded.Should().BeFalse();
        decrypted.Value.Should().BeNull();
        decrypted.Error.Should().Contain("DPAPI decryption failed");
    }

    [Fact]
    public void Decrypt_DefaultEntropy_MigratesLegacyNoEntropyCiphertext()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var plaintext = Encoding.UTF8.GetBytes("legacy-credential");
        var legacyCiphertext = ProtectedData.Protect(
            plaintext,
            optionalEntropy: null,
            DataProtectionScope.CurrentUser);

        var decrypted = DpapiProvider.Decrypt(legacyCiphertext);

        decrypted.Succeeded.Should().BeTrue(decrypted.Error);
        decrypted.Value.Should().Equal(plaintext);
        decrypted.UsedLegacyProtection.Should().BeTrue();
    }

    [Fact]
    public void Operations_ReportUnavailableInsteadOfReturningInput()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }

        var plaintext = Encoding.UTF8.GetBytes("do-not-store-this");

        var encrypted = DpapiProvider.Encrypt(plaintext);
        var decrypted = DpapiProvider.Decrypt(plaintext);

        encrypted.Succeeded.Should().BeFalse();
        encrypted.Value.Should().BeNull();
        decrypted.Succeeded.Should().BeFalse();
        decrypted.Value.Should().BeNull();
    }
}
