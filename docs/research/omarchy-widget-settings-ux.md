# Omarchy widget settings UX research

**Researched:** 2026-08-26

**Scope:** Omarchy Quattro bar widgets, with emphasis on information-dense panels and the Tesla widget

**Decision target:** Move OmaRivian’s `Show percentage in bar` and `Vehicle location` controls out of the bottom of its vehicle-detail feed

## Executive summary

Omarchy does not impose one universal widget-settings interaction. Its shell provides the persistence and metadata contracts—settings live on the widget’s `shell.json` entry, manifests may declare defaults/schema, and plugins can call `shell.updateEntryInline()`—but plugins choose how settings appear.

The source survey found four recurring patterns:

1. **Direct gesture for one tiny display preference.** First-party Power and marketplace Dell Power toggle percentage on right-click.
2. **Host/schema configuration with no custom panel UI.** Tesla and Agent Usage consume manifest settings but do not put a settings page in their popup.
3. **A second view inside the same `KeyboardPanel`.** Detailed Weather exposes a visible **Settings** header action, replaces forecast content with a settings page, and returns through **Done**/Escape.
4. **Settings expanded inside the existing popup.** System Stats opens a settings mode through right-click or **S**; Flight Radar reveals a substantial settings section through **S**. Neither creates another window.

A gear is therefore a valid affordance, but **not an Omarchy convention that automatically opens generic settings**. The clearest precedent for OmaRivian’s problem is Detailed Weather’s visible header action plus same-popup content replacement.

### Recommendation

Use a compact settings action beside **Refresh** that switches the existing `KeyboardPanel` from vehicle details to a dedicated settings page. A gear icon is appropriate for the current 400-unit header, provided it has a `Settings` tooltip; a text **Settings** chip is more directly aligned with Detailed Weather if space permits.

The settings page should:

- keep the same popup, anchor, focus owner, theme, and width;
- show **Back** or **Done** and the title **OmaRivian Settings**;
- persist the two toggles immediately—no Save button is needed for two reversible booleans;
- group `Show percentage in bar` under **Appearance** and `Vehicle location` under **Privacy**;
- move **Re-link** and **Unlink** into an **Account** section because they are also low-frequency configuration;
- return to vehicle details when Escape is pressed from settings, then close on the next Escape;
- reset to vehicle details when the popup closes.

Do **not** open a second layer-shell window. Do **not** rely only on a right-click gesture. Do **not** leave the privacy explanation permanently in the frequently scanned vehicle-detail feed.

## Method

The survey used:

- the official [Omarchy plugin development guide](https://omarchyplugins.com/develop.html), which names the built-in Clock as the closest `bar-widget` + detail-panel example and points to the official shell sources;
- the live [Omarchy Marketplace catalog](https://omarchyplugins.com/catalog.json) to identify representative bar widgets and their repositories;
- installed first-party source under `/usr/share/omarchy/shell`;
- commit-pinned clones of eight marketplace repositories, including Tesla, Detailed Weather, System Stats, Flight Radar, Mouse & Pointer, Dell Power Panel, Agent Usage, and Fan Monitor;
- the current OmaRivian `Panel.qml` as the comparison target.

Marketplace behavior below comes from linked repository source, not screenshots or catalog descriptions alone.

## Platform findings

### Persistence is generic; presentation is plugin-owned

The official shell contract stores settings directly on each `bar.layout` entry. `shell.updateEntryInline(moduleName, settings)` merges and persists those values. Plugin registration carries manifest `defaults`, `schema`, and `settingsForm` metadata into the bar-widget registry. The official CLI also supports `omarchy bar set <id> <key> <value>`.

That is a configuration contract, not a requirement that every popup render a gear or settings page. In the inspected shell snapshot, schema metadata is registered and described as input to a settings panel, while the individual widget still owns its popup. Rich marketplace widgets frequently implement contextual settings themselves.

Sources:

- [Official shell README: settings are inline on plugin entries](https://github.com/basecamp/omarchy/blob/quattro/shell/README.md)
- [Official `shell.qml`: `updateEntryInline` and manifest metadata registration](https://github.com/basecamp/omarchy/blob/quattro/shell/shell.qml)
- [Official plugin development guide](https://omarchyplugins.com/develop.html)

### First-party patterns

| Widget | Settings/configuration UX | Surface |
| --- | --- | --- |
| Power | Right-click toggles the persisted bar percentage; power profile remains an inline operational control | Same widget/popup; no gear |
| Clock | Right-click cycles the persisted clock format; middle-click opens the existing timezone menu | Direct gesture / existing menu |
| Audio | Header mute plus inline volume, device, and application controls | Same popup |
| Bluetooth | Header power toggle plus inline connect/disconnect/forget actions | Same popup |
| Network | Inline Wi-Fi, DNS, band, credentials; separate panels/terminal only for genuinely distinct tasks | Mostly same popup |
| Monitor | Brightness, shell text size, display scale, and monitor controls in one scrollable popup | Same popup |
| Weather (built-in) | Location temporarily becomes an inline editor | Same popup |
| Tailscale | Power toggle and expanding peer/region choices inline | Same popup |

The first-party lesson is not “always use a gear.” It is “avoid a new surface unless the task is meaningfully separate, and make very small preferences cheap to change.”

Representative sources:

- [Power `Panel.qml`](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/panels/power/Panel.qml)
- [Clock `BarWidget.qml`](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/panels/clock/BarWidget.qml)
- [Audio `Panel.qml`](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/panels/audio/Panel.qml)
- [Network `Panel.qml`](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/panels/network/Panel.qml)
- [Monitor `Panel.qml`](https://github.com/basecamp/omarchy/blob/quattro/shell/plugins/panels/monitor/Panel.qml)

## Marketplace case studies

### 1. Tesla: dense information, schema-owned configuration, no panel gear

Tesla is the closest domain and density comparison. Its popup is a single long status view: map, address/activity, battery/range, vehicle facts, and bottom actions such as **Open in maps**, **Refresh**, and conditional **Wake**. Its `Panel.qml` reads eight settings (`vin`, map style/zoom, panel width, polling/throttling, reverse geocoding, and maps URL), but contains no custom settings mode, gear, or `updateEntryInline()` flow.

Those values are declared in the manifest schema and documented in the README’s Settings table. In other words, the Tesla popup is deliberately optimized for “where is my car and what is it doing?” rather than configuration.

This is useful negative evidence for OmaRivian: information density alone does not justify appending preferences to the panel’s bottom.

Sources at surveyed commit `8dac0aa6d85844468b54802cb4feff828d7c6918`:

- [Tesla `Panel.qml`](https://github.com/jankeesvw/omarchy-tesla/blob/8dac0aa6d85844468b54802cb4feff828d7c6918/Panel.qml)
- [Tesla `manifest.json`](https://github.com/jankeesvw/omarchy-tesla/blob/8dac0aa6d85844468b54802cb4feff828d7c6918/manifest.json)
- [Tesla README settings](https://github.com/jankeesvw/omarchy-tesla/blob/8dac0aa6d85844468b54802cb4feff828d7c6918/README.md#settings)

### 2. Detailed Weather: visible Settings → replacement view in the same popup

Detailed Weather is the strongest positive precedent. Its forecast view has **Open radar** at the upper left and a visible **Settings** action at the upper right. Activating Settings changes `mainView` from `"forecast"` to `"settings"` while retaining the same `KeyboardPanel`.

In settings mode:

- the header’s left side becomes **Done**;
- the forecast `Flickable` is hidden and a settings `Flickable` is shown;
- radar site, clock, units, and alerts are grouped into sections;
- simple choices persist immediately via `shell.updateEntryInline()`;
- Escape returns to the forecast before closing the popup.

This pattern directly solves OmaRivian’s issue: occasional controls disappear from the everyday detail scroll without introducing another window or persistence mechanism.

Sources at surveyed commit `986604e0a7275f7060ac18adec7493393c55906f`:

- [Weather view state and header navigation](https://github.com/calebhat/omarchy-weather/blob/986604e0a7275f7060ac18adec7493393c55906f/Panel.qml#L543-L910)
- [Weather settings page](https://github.com/calebhat/omarchy-weather/blob/986604e0a7275f7060ac18adec7493393c55906f/Panel.qml#L1729-L1965)
- [Weather manifest schema](https://github.com/calebhat/omarchy-weather/blob/986604e0a7275f7060ac18adec7493393c55906f/manifest.json)

### 3. System Stats: hidden shortcut/direct gesture → full settings mode

System Stats uses `settingsMode` in the same `KeyboardPanel`:

- right-clicking the bar widget or pressing **S** opens settings;
- the title changes from **System Stats** to **System Stats Settings**;
- normal cards are hidden and a settings layout replaces them;
- settings are edited as draft state;
- **Stats** returns to the main view and **Save** persists the draft;
- status text confirms whether values reached `shell.json` or only the current session.

This is a sound design for numerous interdependent fields. Its weakness for OmaRivian is discoverability: right-click and **S** are too hidden to be the only route to a privacy control.

Sources at surveyed commit `5500990ce9da1d732e58876886c52181d68923cf`:

- [System Stats settings lifecycle](https://github.com/JJDizz1L/dizziee.system-stats/blob/5500990ce9da1d732e58876886c52181d68923cf/Panel.qml#L164-L233)
- [System Stats input and replacement header](https://github.com/JJDizz1L/dizziee.system-stats/blob/5500990ce9da1d732e58876886c52181d68923cf/Panel.qml#L421-L490)
- [System Stats settings content](https://github.com/JJDizz1L/dizziee.system-stats/blob/5500990ce9da1d732e58876886c52181d68923cf/Panel.qml#L806-L995)

### 4. Flight Radar: keyboard-disclosed settings appended in the same popup

Flight Radar has enough configuration to justify a substantial custom editor. Pressing **S** toggles `settingsOpen`; a keycap legend advertises the shortcut. The settings section includes many fields, Save/Reset actions, notices, and optional account credentials. Closing the popup clears `settingsOpen`.

Unlike Weather and System Stats, the settings content is conditionally inserted into the same larger scrolling column rather than replacing the whole main view. This works for a specialist, keyboard-oriented panel but would recreate OmaRivian’s vertical-density problem if copied directly.

Sources at surveyed commit `e817fc695a6985c483706a2d8bb2789cc467ef22`:

- [Flight Radar keyboard toggle](https://github.com/yuters/omarchy-flight-radar/blob/e817fc695a6985c483706a2d8bb2789cc467ef22/Panel.qml#L1697-L1732)
- [Flight Radar settings section and actions](https://github.com/yuters/omarchy-flight-radar/blob/e817fc695a6985c483706a2d8bb2789cc467ef22/Panel.qml#L1924-L2150)

### 5. Mouse & Pointer: a literal header gear launches an external editor

Mouse & Pointer is the clearest sampled example of a gear in the popup header. It is an actual bordered gear button, but it does **not** switch to an in-panel settings page. It runs:

```text
omarchy-launch-config-editor ~/.config/hypr/input.lua
```

The panel itself is already a graphical settings tool with Motion, Scrolling, and Buttons tabs. The gear means “open the underlying config file,” not “show this panel’s normal settings.”

This supports using a gear as recognizable configuration chrome, but it also shows why behavior must be made clear with a tooltip and navigation title.

Source at surveyed commit `b96e6d392b584a2732b1f2df0db33ba649d9f989`:

- [Mouse & Pointer gear and editor process](https://github.com/meviusisback/mouse-settings/blob/b96e6d392b584a2732b1f2df0db33ba649d9f989/Panel.qml#L100-L114)
- [Mouse & Pointer header button](https://github.com/meviusisback/mouse-settings/blob/b96e6d392b584a2732b1f2df0db33ba649d9f989/Panel.qml#L312-L338)

### 6. Dell Power: direct gesture for the exact “show percentage” class of setting

Dell Power mirrors the first-party Power behavior. `showPercentage` is persisted through `updateEntryInline()`, and right-clicking the bar widget toggles it immediately. There is no dedicated settings page.

That makes right-click a reasonable optional shortcut for OmaRivian’s percentage display, but not a sufficient primary interface because it is undiscoverable and cannot responsibly carry the location privacy explanation.

Source at surveyed commit `3d2b19a7354cd4f5daba856758b0a6d870b7605b`:

- [Dell Power percentage toggle and right-click](https://github.com/stappmus/omarchy-dell-power-profiles/blob/3d2b19a7354cd4f5daba856758b0a6d870b7605b/Panel.qml#L365-L383)
- [Dell Power bar input](https://github.com/stappmus/omarchy-dell-power-profiles/blob/3d2b19a7354cd4f5daba856758b0a6d870b7605b/Panel.qml#L554-L565)

### 7. Agent Usage and Fan Monitor: schema-only or no settings

Agent Usage declares a refresh interval in its manifest and consumes it in its service, while its panel remains a read-only information surface. Fan Monitor is likewise a read-only monitoring popup with no custom settings UI. These reinforce the separation between daily information and infrequent configuration.

Sources:

- [Agent Usage manifest at `bf0f97a…`](https://github.com/robzolkos/omarchy-agent-usage/blob/bf0f97a99f30abb39c35695039d1b59374e28bf4/manifest.json)
- [Agent Usage panel at `bf0f97a…`](https://github.com/robzolkos/omarchy-agent-usage/blob/bf0f97a99f30abb39c35695039d1b59374e28bf4/Panel.qml)
- [Fan Monitor panel at `0c0b457…`](https://github.com/elynch303/fan-monitor/blob/0c0b45716517f50f668e4df51e725130ebde628e/Panel.qml)

## Pattern matrix

| Example | Entry affordance | Settings behavior | Persistence style | Fit for OmaRivian |
| --- | --- | --- | --- | --- |
| Tesla | Host/schema outside panel | No custom settings UI | Manifest values consumed by panel | Good separation, but too remote for privacy/link controls |
| Detailed Weather | Visible **Settings** header action | Replaces content in same popup; **Done**/Escape returns | Immediate | **Best match** |
| System Stats | Right-click or **S** | Replaces main content in same popup | Draft + Save | Good structure; entry is too hidden |
| Flight Radar | Advertised **S** shortcut | Expands settings in same scroll | Save/Reset | Too vertically heavy for this case |
| Mouse & Pointer | Header gear | Opens external config editor | External file | Gear precedent, wrong surface behavior |
| Power / Dell Power | Right-click | Toggles percentage directly | Immediate | Good optional shortcut only |
| Agent Usage / Fan Monitor | None in popup | Schema-only or no settings | Host/defaults | Supports keeping read-only panels focused |

## OmaRivian assessment

The current implementation is correct at the storage and privacy layers. `persistSettings()` merges the current widget entry, updates the host binding, and calls `shell.updateEntryInline()`. Disabling location also synchronizes the helper and cached state.

The UX issue is placement:

- the vehicle popup is already a long, frequently scanned status feed;
- the two low-frequency toggles sit after vehicle facts and permanently lengthen that feed;
- the location description adds necessary privacy context, but that text becomes permanent visual weight;
- Re-link/Unlink are also configuration rather than vehicle status;
- the scroll fix makes the controls reachable, but does not make the information architecture cleaner.

## Recommended OmaRivian design

### Detail view

Keep the present vehicle-detail content. Change the header’s right-side controls to:

```text
[vehicle title and status]              [Refresh] [gear]
```

If the text chip fits comfortably, prefer `[Settings]` over a bare gear because it follows Detailed Weather and is more discoverable. If compactness wins, use the same gear glyph family seen in Mouse & Pointer, with:

- tooltip: `Settings`;
- pointing cursor and visible hover/focus treatment;
- keyboard activation;
- an accessible/settings title in the destination view.

### Settings view

Replace the detail `Flickable` content; do not append to it:

```text
[Done / Back]                  OmaRivian Settings
--------------------------------------------------
APPEARANCE
Show percentage in bar                          [toggle]

PRIVACY
Vehicle location                                [toggle]
Saves current coordinates on this device. Shared with
OpenStreetMap only when you open a map.

ACCOUNT
[Re-link account]                         [Unlink…]
```

Behavior:

- toggles apply and persist immediately;
- location remains disabled while the helper is busy, as today;
- unlink retains its current confirmation step;
- Escape/back returns to details before closing;
- closing the popup clears settings view and unlink confirmation;
- Refresh is hidden in settings because it is an operational vehicle action.

### QML shape for a future implementation

Keep one `KeyboardPanel` and one `PanelKeyCatcher`. Add a page-state property such as:

```qml
property string page: "details" // "details" | "settings"
```

Then use one of:

1. **Two mutually exclusive page roots** (`visible`/`enabled`)—most similar to Detailed Weather and easiest to review.
2. **`Loader.sourceComponent`**—keeps only the active page contributing implicit size and reduces the live object tree.
3. **`StackLayout.currentIndex`**—convenient if both page trees should retain transient state.

For only two pages, mutually exclusive roots or a `Loader` are simpler than introducing a navigation framework. Preserve the current `persistSettings()`, toggle handlers, helper synchronization, and `Flickable`; this is an information-architecture change, not a storage redesign.

## Alternatives considered

### Keep the bottom settings section

**Pros:** simplest code, all controls visible.

**Cons:** settings remain mixed with telemetry, account actions stay buried, privacy copy lengthens every visit, and future settings scale poorly.

**Decision:** reject as the long-term design.

### Right-click percentage; location elsewhere

**Pros:** strongly supported by Power/Dell Power and very fast for experienced users.

**Cons:** hidden gesture, inconsistent routes for two settings, poor home for privacy explanation.

**Decision:** optional enhancement only, never the sole interface.

### Use only manifest/schema or `omarchy bar set`

**Pros:** no custom settings page and aligns with Tesla/Agent Usage.

**Cons:** too remote for a setting that controls locally retained location data; account lifecycle does not fit schema fields well.

**Decision:** retain schema/CLI compatibility if desired, but provide contextual in-panel settings.

### Launch a separate settings window

**Pros:** maximum room and isolation.

**Cons:** duplicate anchoring/focus/lifecycle work, visual discontinuity, and disproportionate complexity for two toggles and account actions. Omarchy examples reserve separate surfaces for distinct tasks, not ordinary widget preferences.

**Decision:** reject.

## Final decision

Adopt **visible header settings action → same-popup replacement settings page → immediate persistence → Done/Escape back**.

This combines the best evidence:

- Tesla’s discipline of keeping vehicle telemetry focused;
- Detailed Weather’s discoverable same-panel navigation;
- Power/Dell Power’s immediate persistence for a percentage preference;
- Mouse & Pointer’s compact gear affordance;
- Omarchy’s existing inline-entry persistence contract.

It is cleaner than the current bottom rows, more discoverable than a right-click-only shortcut, and substantially simpler than a separate panel or window.
