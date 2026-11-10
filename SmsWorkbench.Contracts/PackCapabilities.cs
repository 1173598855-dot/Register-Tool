// Opted into nullable reference checking file-by-file - see the note in
// PaymentBatchService.cs for why the project-wide switch stays `annotations`.
#nullable enable

namespace SmsWorkbench
{
    /// <summary>
    /// Which desktop actions the selected registration pack can actually serve.
    /// </summary>
    /// <remarks>
    /// A pack is one registration architecture, and its manifest declares the
    /// capabilities it claims (<c>sms_tool/packs/contracts.py</c> owns the
    /// vocabulary). The desktop used to render every action unconditionally, which
    /// was only correct while there was exactly one pack that declared everything:
    /// the moment a second architecture lands without <c>payment.link</c>, its
    /// payment rows would open a command the backend has no entrypoint for.
    ///
    /// Three deliberate choices, each of which is a fallback rather than a rule:
    ///
    /// * <b>No payload, no pact.</b> A missing or unreadable <c>--pack-list --json</c>
    ///   answer reads as <see cref="AllowAll"/>. A capability probe that fails must
    ///   not hide the operator's own tools -- it is a UI nicety, not a permission.
    /// * <b>Ambiguity resolves to AllowAll, never to "the first pack".</b> With more
    ///   than one enabled pack the desktop has no basis to pick one; the backend's
    ///   own selector refuses the same situation with exit 2 and names both remedies
    ///   (<c>--pack</c> / <c>GPT_PACK_ID</c>). Guessing here would be a routing
    ///   decision nobody made.
    /// * <b>Only the gated rows are gated.</b> Settings, theme, language, proxy pool
    ///   and the workspace tools stay visible whatever the pack declares, so an
    ///   operator can always repair a broken install from inside the app.
    /// </remarks>
    public sealed class PackCapabilities
    {
        /// <summary>Capability names this projection understands (manifest vocabulary).</summary>
        public const string AccountHealth = "account.health";
        public const string MailboxOtp = "mailbox.otp";
        public const string PaymentLink = "payment.link";

        /// <summary>
        /// Nav key (<c>MainWindow.NavActions</c>) -> the capability it needs. Keys
        /// absent from this map are never gated; add one only when the action
        /// genuinely cannot work without the capability.
        /// </summary>
        private static readonly IReadOnlyDictionary<string, string> ActionRequirements =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["paylink"] = PaymentLink,
                ["batchpay"] = PaymentLink,
                ["paymentqualification"] = PaymentLink,
                ["sms"] = MailboxOtp,
                ["inbox"] = MailboxOtp,
                ["scan"] = AccountHealth,
            };

        private readonly HashSet<string>? declared;

        private PackCapabilities(HashSet<string>? declared, string source)
        {
            this.declared = declared;
            Source = source;
        }

        /// <summary>Every gated nav key, mapped to its capability. Read-only for tests and docs.</summary>
        public static IReadOnlyDictionary<string, string> GatedActions => ActionRequirements;

        /// <summary>True when nothing is gated (no payload, or an ambiguous pack set).</summary>
        public bool IsUnrestricted => declared == null;

        /// <summary>The capability names the single enabled pack declares (empty when unrestricted).</summary>
        public IReadOnlyCollection<string> Declared =>
            declared == null ? Array.Empty<string>() : declared;

        /// <summary>Why this projection is what it is, for the console line and for tests.</summary>
        public string Source { get; }

        public static PackCapabilities AllowAll { get; } = new PackCapabilities(null, "no capability restriction");

        /// <summary>True when the pack declares <paramref name="capability"/>.</summary>
        public bool Declares(string capability)
        {
            return declared != null && declared.Contains(capability ?? "");
        }

        /// <summary>True when this nav key is capability-gated at all.</summary>
        public bool IsGated(string action)
        {
            return ActionRequirements.ContainsKey(action ?? "");
        }

        /// <summary>The capability <paramref name="action"/> needs, or null when it is not gated.</summary>
        public string? RequiredCapability(string action)
        {
            return ActionRequirements.TryGetValue(action ?? "", out string? capability) ? capability : null;
        }

        /// <summary>
        /// Whether <paramref name="action"/> may be offered. An unknown or ungated key
        /// is always allowed: the gate is a subtraction from the current UI, not a
        /// whitelist that would hide rows nobody remembered to list.
        /// </summary>
        public bool Allows(string action)
        {
            string? required = RequiredCapability(action);
            if (required == null || declared == null)
            {
                return true;
            }

            return declared.Contains(required);
        }

        /// <summary>
        /// Project the <c>--pack-list --json</c> payload onto a capability set.
        /// </summary>
        /// <remarks>
        /// Reads the fields the backend actually emits (verified against
        /// <c>python -m sms_tool --pack-list --json</c>): a top-level <c>packs</c>
        /// array whose entries carry <c>id</c>, <c>enabled</c> and
        /// <c>capabilities</c>. Anything unexpected -- absent payload, absent array,
        /// zero enabled packs, more than one -- reads as <see cref="AllowAll"/> and
        /// says so in <see cref="Source"/>.
        /// </remarks>
        public static PackCapabilities FromPackList(JsonElement? payload)
        {
            if (payload is not { ValueKind: JsonValueKind.Object })
            {
                return new PackCapabilities(null, "no pack-list payload: every action stays available");
            }

            if (!payload.Value.TryGetProperty("packs", out JsonElement packs) || packs.ValueKind != JsonValueKind.Array)
            {
                return new PackCapabilities(null, "pack-list payload has no 'packs' array: every action stays available");
            }

            List<JsonElement> enabled = new List<JsonElement>();
            foreach (JsonElement pack in packs.EnumerateArray())
            {
                if (pack.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }

                // `enabled` is what the manifest's status resolves to; a pack that is
                // disabled cannot serve any command, so it must not shape the UI.
                if (pack.TryGetProperty("enabled", out JsonElement enabledElement)
                    && enabledElement.ValueKind == JsonValueKind.False)
                {
                    continue;
                }

                enabled.Add(pack);
            }

            if (enabled.Count != 1)
            {
                string reason = enabled.Count == 0
                    ? "no enabled pack: every action stays available"
                    : $"{enabled.Count} enabled packs: the desktop will not pick one, every action stays available";
                return new PackCapabilities(null, reason);
            }

            JsonElement single = enabled[0];
            string id = single.TryGetProperty("id", out JsonElement idElement) ? idElement.GetString() ?? "" : "";
            HashSet<string> capabilities = new HashSet<string>(StringComparer.Ordinal);
            if (single.TryGetProperty("capabilities", out JsonElement declaredElement)
                && declaredElement.ValueKind == JsonValueKind.Array)
            {
                foreach (JsonElement capability in declaredElement.EnumerateArray())
                {
                    if (capability.ValueKind == JsonValueKind.String)
                    {
                        string? value = capability.GetString();
                        if (!string.IsNullOrEmpty(value))
                        {
                            capabilities.Add(value!);
                        }
                    }
                }
            }

            return new PackCapabilities(capabilities, $"pack '{id}' declares {capabilities.Count} capability(ies)");
        }
    }
}
