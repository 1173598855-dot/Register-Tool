using System.Text.Json;

namespace SmsWorkbench.Tests;

/// <summary>
/// The desktop renders by pack capability (Phase 5.1), and these tests pin the two
/// things that can go wrong invisibly: gating an action the pack does declare, and
/// gating anything at all on a payload the desktop could not read.
/// </summary>
public sealed class PackCapabilitiesTests
{
    private static JsonElement Payload(string json) => JsonDocument.Parse(json).RootElement.Clone();

    private static string PackList(string packsJson) =>
        "{\"ok\": true, \"packs\": [" + packsJson + "]}";

    private static string Pack(string id, string[] capabilities, bool enabled = true) =>
        "{\"id\": \"" + id + "\", \"enabled\": " + (enabled ? "true" : "false") +
        ", \"capabilities\": [" + string.Join(", ", capabilities.Select(c => "\"" + c + "\"")) + "]}";

    [Fact]
    public void A_pack_that_only_declares_account_health_hides_payment_and_sms()
    {
        // The case the whole phase exists for: a second architecture that registers
        // accounts but sells nothing and reads no mailboxes.
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(Pack("acme.portal", new[] { "account.health" }))));

        Assert.True(capabilities.Allows("scan"), "account.health is declared, so the health scan stays");
        Assert.False(capabilities.Allows("paylink"), "no payment.link, so the PayPal link row must go");
        Assert.False(capabilities.Allows("batchpay"), "no payment.link, so the batch payment row must go");
        Assert.False(capabilities.Allows("paymentqualification"), "no payment.link, so the qualification row must go");
        Assert.False(capabilities.Allows("sms"), "no mailbox.otp, so one-click 接码 must go");
        Assert.False(capabilities.Allows("inbox"), "no mailbox.otp, so the inbox row must go");
    }

    [Fact]
    public void A_pack_that_declares_everything_keeps_every_row()
    {
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(Pack("openai.chatgpt", new[]
            {
                "account.health", "account.registration.email", "mailbox.otp",
                "payment.batch", "payment.link", "session.access_token",
            }))));

        Assert.True(capabilities.IsUnrestricted == false);
        foreach (string action in PackCapabilities.GatedActions.Keys)
        {
            Assert.True(capabilities.Allows(action), action + " should stay visible");
        }
    }

    [Fact]
    public void Rows_that_need_no_capability_are_never_gated()
    {
        // Settings, theme, language, proxy pool, workspace tools: the operator must
        // be able to repair a broken install from inside the app.
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(Pack("acme.portal", Array.Empty<string>()))));

        foreach (string action in new[] { "settings", "theme", "language", "proxypool", "backup", "restore", "register" })
        {
            Assert.False(capabilities.IsGated(action), action + " must not be gated");
            Assert.True(capabilities.Allows(action));
        }
    }

    [Fact]
    public void An_unreadable_payload_gates_nothing()
    {
        // A capability probe that fails must never take the operator's tools away.
        foreach (JsonElement? payload in new JsonElement?[] { null, Payload("[]"), Payload("{}"), Payload("{\"packs\": 3}") })
        {
            PackCapabilities capabilities = PackCapabilities.FromPackList(payload);
            Assert.True(capabilities.IsUnrestricted);
            foreach (string action in PackCapabilities.GatedActions.Keys)
            {
                Assert.True(capabilities.Allows(action), action + " must stay available without a payload");
            }
        }
    }

    [Fact]
    public void Two_enabled_packs_are_never_resolved_by_order()
    {
        // The backend refuses this situation with exit 2 and names --pack / GPT_PACK_ID.
        // The desktop must not invent the answer the backend refused to invent.
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(
                Pack("a.one", new[] { "account.health" }) + "," +
                Pack("b.two", new[] { "payment.link" }))));

        Assert.True(capabilities.IsUnrestricted);
        Assert.Contains("2 enabled packs", capabilities.Source, StringComparison.Ordinal);
    }

    [Fact]
    public void A_disabled_pack_does_not_shape_the_ui()
    {
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(
                Pack("retired.one", new[] { "payment.link" }, enabled: false) + "," +
                Pack("acme.portal", new[] { "account.health" }))));

        Assert.False(capabilities.IsUnrestricted);
        Assert.False(capabilities.Allows("paylink"));
        Assert.True(capabilities.Allows("scan"));
    }

    [Fact]
    public void The_declared_set_is_reported_for_the_console_line()
    {
        PackCapabilities capabilities = PackCapabilities.FromPackList(
            Payload(PackList(Pack("acme.portal", new[] { "account.health", "mailbox.otp" }))));

        Assert.Contains("acme.portal", capabilities.Source, StringComparison.Ordinal);
        Assert.Equal(2, capabilities.Declared.Count);
        Assert.True(capabilities.Declares("mailbox.otp"));
        Assert.False(capabilities.Declares("payment.link"));
    }

    [Fact]
    public void The_gate_covers_three_capabilities_and_six_rows()
    {
        // A guard on the map itself: adding a gated row without deciding its
        // capability would silently gate it on nothing.
        Assert.Equal(
            new[] { "account.health", "mailbox.otp", "payment.link" }.OrderBy(name => name, StringComparer.Ordinal),
            PackCapabilities.GatedActions.Values.Distinct().OrderBy(name => name, StringComparer.Ordinal));
        Assert.Equal(6, PackCapabilities.GatedActions.Count);
    }
}
