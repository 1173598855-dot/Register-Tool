// Opted into nullable reference checking file-by-file - see the note in
// PaymentBatchService.cs for why the project-wide switch used to stay `annotations`.
#nullable enable

namespace SmsWorkbench
{
    /// <summary>
    /// Sidebar visuals (brand, navigation, collapse button).
    ///
    /// The column width and its animation stay on <see cref="MainWindow"/>:
    /// <c>SidebarColumn</c> is a column definition of the window grid, so the
    /// control cannot own it. <see cref="IsCollapsed"/> drives every visual
    /// trigger inside the control; the button only raises
    /// <see cref="ToggleRequested"/> and lets the window flip
    /// <c>SidebarCollapsed</c>, which keeps one owner for the state.
    /// </summary>
    public partial class Sidebar : UserControl
    {
        public static readonly DependencyProperty IsCollapsedProperty = DependencyProperty.Register(
            nameof(IsCollapsed),
            typeof(bool),
            typeof(Sidebar),
            new PropertyMetadata(false));

        /// <summary>
        /// <c>CommandParameter</c> of the row whose action is running, or empty.
        /// Each row compares it against its own parameter (see
        /// <c>IconNavButtonStyle</c>); the sidebar owns no state of its own.
        /// </summary>
        public static readonly DependencyProperty ActiveKeyProperty = DependencyProperty.Register(
            nameof(ActiveKey),
            typeof(string),
            typeof(Sidebar),
            new PropertyMetadata(string.Empty));

        public static readonly RoutedEvent ToggleRequestedEvent = EventManager.RegisterRoutedEvent(
            nameof(ToggleRequested),
            RoutingStrategy.Bubble,
            typeof(RoutedEventHandler),
            typeof(Sidebar));

        public Sidebar()
        {
            InitializeComponent();
        }

        public bool IsCollapsed
        {
            get => (bool)GetValue(IsCollapsedProperty);
            set => SetValue(IsCollapsedProperty, value);
        }

        public string ActiveKey
        {
            get => (string)GetValue(ActiveKeyProperty);
            set => SetValue(ActiveKeyProperty, value);
        }

        public event RoutedEventHandler ToggleRequested
        {
            add => AddHandler(ToggleRequestedEvent, value);
            remove => RemoveHandler(ToggleRequestedEvent, value);
        }

        private void Toggle_Click(object sender, RoutedEventArgs e)
            => RaiseEvent(new RoutedEventArgs(ToggleRequestedEvent, this));

        /// <summary>
        /// Hide the navigation rows whose action the enabled pack cannot serve.
        /// </summary>
        /// <remarks>
        /// Hides rather than disables: a row that can never work in this build is
        /// noise, and a permanently greyed row still costs a slot in a 19-row
        /// sidebar. The decision itself lives in <see cref="PackCapabilities"/>
        /// (pure, xunit-tested); this method only applies it to the buttons whose
        /// <c>CommandParameter</c> is a gated nav key, and leaves every other row
        /// alone -- an unknown key is never hidden by omission.
        /// </remarks>
        public void ApplyPackCapabilities(PackCapabilities capabilities)
        {
            ArgumentNullException.ThrowIfNull(capabilities);
            foreach (IconNavButton button in EnumerateNavButtons(this))
            {
                string key = button.CommandParameter as string ?? string.Empty;
                button.Visibility = capabilities.Allows(key) ? Visibility.Visible : Visibility.Collapsed;
            }
        }

        /// <summary>
        /// Every <see cref="IconNavButton"/> under <paramref name="root"/>, by visual
        /// tree. The rows are static XAML (not an ItemsControl), so there is no
        /// collection to rebind -- the tree is the only enumeration point.
        /// </summary>
        private static IEnumerable<IconNavButton> EnumerateNavButtons(DependencyObject root)
        {
            int count = VisualTreeHelper.GetChildrenCount(root);
            for (int index = 0; index < count; index++)
            {
                DependencyObject child = VisualTreeHelper.GetChild(root, index);
                if (child is IconNavButton button)
                {
                    yield return button;
                }

                foreach (IconNavButton nested in EnumerateNavButtons(child))
                {
                    yield return nested;
                }
            }
        }
    }
}
