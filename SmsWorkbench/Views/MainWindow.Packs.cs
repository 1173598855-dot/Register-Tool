// Opted into nullable reference checking file-by-file - see the note in
// PaymentBatchService.cs for why the project-wide switch stays `annotations`.
#nullable enable

namespace SmsWorkbench
{
    public partial class MainWindow
    {
        /// <summary>How long the one capability probe at startup may take.</summary>
        private const int PackListTimeoutMilliseconds = 30000;

        /// <summary>What the sidebar was last gated on; also the value tests can read.</summary>
        private PackCapabilities packCapabilities = PackCapabilities.AllowAll;

        /// <summary>
        /// Run the probe once, after the first render.
        /// </summary>
        /// <remarks>
        /// <c>OnContentRendered</c> rather than a <c>Loaded</c> subscription on
        /// purpose: the gate walks the sidebar's visual tree, which only exists once
        /// the window has rendered, and a partial can override this without adding a
        /// line to the composition root (whose ceiling is a pinned number in
        /// <c>PartialSizeTests</c>). It fires once, and only for a window that is
        /// actually shown -- so the window smoke tests never issue a subprocess.
        /// </remarks>
        protected override void OnContentRendered(EventArgs e)
        {
            base.OnContentRendered(e);
            _ = ApplyPackCapabilitiesAsync();
        }

        /// <summary>
        /// Read the installed packs once, and hide the rows the enabled pack cannot serve.
        /// </summary>
        /// <remarks>
        /// This is the desktop half of Phase 5.1: the backend already declares which
        /// capabilities each architecture claims, and <c>--pack-list --json</c> is the
        /// read-only inventory of exactly that. Gating the rows is what stops a second
        /// architecture's build from offering payment or 接码 actions the backend has no
        /// entrypoint for.
        ///
        /// Two failure paths, both of which leave today's behaviour intact: the probe
        /// itself throws (no interpreter, timeout) and the payload is unreadable --
        /// both resolve to <see cref="PackCapabilities.AllowAll"/>, so a capability
        /// probe can never take tools away from the operator. It runs once per launch,
        /// with no polling and no re-probe when a batch starts (a pack cannot change
        /// under a running process).
        /// </remarks>
        private async Task ApplyPackCapabilitiesAsync()
        {
            try
            {
                BackendCommandPlan plan = BackendCommandPlanner.CreatePackList();
                BackendCommand command = BackendCommand.Create(
                    plan.TaskName,
                    plan.Arguments,
                    timeoutMilliseconds: PackListTimeoutMilliseconds);
                BackendCommandResult result = await backendClient.RunAsync(command).ConfigureAwait(true);
                packCapabilities = PackCapabilities.FromPackList(result.Payload);
            }
            catch
            {
                packCapabilities = PackCapabilities.AllowAll;
            }

            try
            {
                // Resolved by name rather than cached in a field: the XAML name is the
                // one place the control is identified, and the lookup keeps this
                // partial from needing constructor wiring.
                (FindName("SidebarControl") as Sidebar)?.ApplyPackCapabilities(packCapabilities);
            }
            catch
            {
                // A visual-tree race must never take the window down. The rows simply
                // stay visible, which is the pre-5.1 behaviour.
            }
        }
    }
}
