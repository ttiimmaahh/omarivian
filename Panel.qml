import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: panel

  moduleName: "io.github.ttiimmaahh.omarivian"
  ipcTarget: "omarivian"
  manageIpc: false

  property Item anchorItem: null
  property var hostWidget: null

  // Read-only view state; this panel never sends commands to the vehicle.
  property var stateData: Model.emptyState("loading", "")
  property var lastGood: null
  // Artwork is not part of the normalized model, so keep the last good local
  // render per vehicle id alongside lastGood and let it survive a failed poll.
  property var artworkById: ({})
  property string overrideVehicleId: ""
  property bool busy: false
  property string helperError: ""
  property bool confirmUnlink: false
  // Which page the single popup shows: "details" | "settings".
  property string page: "details"
  property bool settingsReady: false
  property string queuedLocationArg: ""
  property string pluginVersion: ""
  property double nowMs: Date.now()

  readonly property string pluginDir: {
    const u = Qt.resolvedUrl(".").toString();
    const path = u.startsWith("file://") ? u.substring(7) : u;
    return path.endsWith("/") ? path : path + "/";
  }
  readonly property string helperPath: panel.pluginDir + "tools/omarivian"
  readonly property string statePath: {
    const explicit = Quickshell.env("XDG_STATE_HOME");
    const base = (explicit && explicit.length > 0) ? explicit : (Quickshell.env("HOME") + "/.local/state");
    return base + "/omarivian/state.json";
  }
  readonly property string omarchyPath: Quickshell.env("OMARCHY_PATH") || "/usr/share/omarchy"

  readonly property bool useImperial: Model.imperial(panel.settings, Qt.locale().name)
  readonly property bool showChargeInBar: panel.setting("showChargeInBar", false) === true
  readonly property bool locationEnabled: panel.setting("locationEnabled", false) === true
  readonly property string kind: Model.statusKind(panel.stateData)
  // Fall back to the last good payload so a transient error keeps numbers on screen.
  readonly property var shownState: (panel.kind === "ok" && panel.stateData.vehicles.length > 0) ? panel.stateData : (panel.lastGood || panel.stateData)
  readonly property var vehicle: Model.selectVehicle(panel.shownState, panel.overrideVehicleId)
  readonly property bool hasData: !!panel.vehicle
  readonly property var activity: Model.vehicleActivity(panel.vehicle)
  readonly property string artworkUrl: {
    if (!panel.hasData)
      return "";
    const found = panel.artworkById[panel.vehicle.id];
    return (typeof found === "string") ? found : "";
  }
  readonly property bool stale: panel.hasData && (panel.kind !== "ok" || Model.isStale(panel.shownState, panel.nowMs, panel.settings ? panel.settings.refreshIntervalSec : 900))

  // Derived tints so the panel stays inside the theme's four colors.
  readonly property color mutedForeground: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.6)
  readonly property color subtleSurface: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.08)
  readonly property color hairline: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.16)

  // Activity tones. No theme color means "charging" or "driving", so those two
  // hues are fixed, and each has a light-background and a dark-background
  // variant so the activity line clears 4.5:1 against either. Weighted channels
  // are enough to tell the two apart; this is a polarity test, not a measurement.
  readonly property bool darkTheme: (Color.background.r * 0.2126 + Color.background.g * 0.7152 + Color.background.b * 0.0722) < 0.5
  readonly property color chargingTone: panel.darkTheme ? "#4ade80" : "#15803d"
  readonly property color drivingTone: panel.darkTheme ? "#60a5fa" : "#1d4ed8"
  // Sleeping stays quiet, but sits above mutedForeground: a prominent line has
  // to stay readable, and 60% foreground does not on most themes.
  readonly property color idleTone: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.78)

  function activityTone(tone) {
    if (tone === "charging")
      return panel.chargingTone;
    if (tone === "driving")
      return panel.drivingTone;
    if (tone === "idle")
      return panel.idleTone;
    return Color.foreground;
  }
  function refresh() {
    panel.runHelper(["refresh", panel.locationEnabled ? "--location" : "--no-location"]);
  }
  function selectVehicleId(id) {
    if (helper.running)
      return;
    panel.overrideVehicleId = id;
    panel.runHelper(["select", id]);
  }
  function persistSettings(values) {
    const entry = { id: panel.moduleName };
    for (const existing in panel.settings)
      if (existing !== "id")
        entry[existing] = panel.settings[existing];
    for (const key in values)
      entry[key] = values[key];

    // settings is bound to the host widget; update the host so the binding
    // remains intact and later changes from Omarchy continue to propagate.
    if (panel.hostWidget && "settings" in panel.hostWidget)
      panel.hostWidget.settings = entry;
    if (panel.bar && panel.bar.shell && typeof panel.bar.shell.updateEntryInline === "function")
      panel.bar.shell.updateEntryInline(panel.moduleName, entry);
  }
  function setShowChargeInBar(value) {
    panel.persistSettings({ showChargeInBar: value });
  }
  function setLocationEnabled(value) {
    panel.persistSettings({ locationEnabled: value });
  }
  function syncLocationPreference() {
    const arg = panel.locationEnabled ? "--location" : "--no-location";
    if (helper.running) {
      panel.queuedLocationArg = arg;
      return;
    }
    panel.runHelper(["refresh", arg, "--location-generation", String(Date.now())]);
  }
  function unlink() {
    if (helper.running)
      return;
    panel.confirmUnlink = false;
    panel.runHelper(["unlink"]);
  }
  function link() {
    panel.close();
    Quickshell.execDetached([panel.omarchyPath + "/bin/omarchy-launch-terminal", panel.pluginDir + "tools/omarivian", "link"]);
  }
  function runHelper(args) {
    if (helper.running)
      return;
    panel.helperError = "";
    panel.busy = true;
    helper.command = [panel.helperPath].concat(args);
    helper.running = true;
  }
  function applyText(body) {
    const parsed = Model.parseState(body);
    panel.stateData = parsed;
    if (Model.statusKind(parsed) === "unlinked") {
      panel.lastGood = null;
      panel.artworkById = ({});
      panel.overrideVehicleId = "";
    } else if (Model.statusKind(parsed) === "ok" && parsed.vehicles.length > 0) {
      panel.lastGood = parsed;
      panel.artworkById = panel.artworkFromText(body);
    }
    panel.nowMs = Date.now();
    // Privacy wins during startup too: an old location-bearing state can
    // outlive a shell.json edit made while the shell was not running.
    if (!panel.locationEnabled && parsed.locationEnabled === true)
      panel.syncLocationPreference();
  }
  // The helper caches the vehicle render locally and reports it as a file URL.
  // Only local files are kept, so the panel never reaches out to the network.
  function artworkFromText(body) {
    const found = {};
    try {
      const raw = JSON.parse(body);
      const list = (raw && Array.isArray(raw.vehicles)) ? raw.vehicles : [];
      for (let i = 0; i < list.length; i++) {
        const item = list[i];
        if (!item || typeof item.id !== "string" || item.id === "")
          continue;
        if (typeof item.artwork === "string" && item.artwork.startsWith("file://"))
          found[item.id] = item.artwork;
      }
    } catch (error) {
      return found;
    }
    return found;
  }
  function applyManifestText(body) {
    try {
      const parsed = JSON.parse(body);
      panel.pluginVersion = (parsed && typeof parsed.version === "string") ? parsed.version.trim() : "";
    } catch (error) {
      panel.pluginVersion = "";
    }
  }

  Component.onCompleted: panel.settingsReady = true

  onLocationEnabledChanged: {
    if (panel.settingsReady)
      panel.syncLocationPreference();
  }

  onOpenedChanged: {
    // Every open starts on vehicle details with no pending destructive step,
    // and closing drops the same state so a reopen can never resume mid-flow.
    panel.page = "details";
    panel.confirmUnlink = false;
    if (!panel.opened)
      return;
    panel.nowMs = Date.now();
    panel.refresh();
  }

  FileView {
    path: panel.pluginDir + "manifest.json"
    onLoaded: panel.applyManifestText(text())
    onLoadFailed: panel.pluginVersion = ""
  }

  FileView {
    id: stateFile

    path: panel.statePath
    watchChanges: true
    onFileChanged: reload()
    onLoaded: panel.applyText(text())
    onLoadFailed: panel.stateData = Model.emptyState("unlinked", "No state file yet.")
  }

  Process {
    id: helper

    running: false
    stdout: StdioCollector {}
    stderr: StdioCollector {
      id: helperErr
    }
    onExited: function (exitCode) {
      panel.busy = false;
      panel.nowMs = Date.now();
      const stderrText = (helperErr.text || "").trim();
      // The helper writes a structured state for expected nonzero outcomes
      // (unlinked, expired auth, unavailable API). Only surface stderr when
      // the process itself failed before it could update that state.
      if (exitCode > 3 && stderrText !== "")
        panel.helperError = stderrText.split("\n").pop();
      else
        panel.helperError = "";
      stateFile.reload();
      if (panel.queuedLocationArg !== "") {
        const arg = panel.queuedLocationArg;
        panel.queuedLocationArg = "";
        panel.runHelper(["refresh", arg, "--location-generation", String(Date.now())]);
      }
    }
  }

  Timer {
    interval: Model.refreshIntervalSec(panel.settings) * 1000
    running: true
    repeat: true
    onTriggered: panel.refresh()
  }

  Timer {
    interval: 60000
    running: true
    repeat: true
    onTriggered: panel.nowMs = Date.now()
  }

  component Chip: Rectangle {
    id: chip

    property string label: ""
    property bool active: false
    property bool danger: false
    property bool iconOnly: false
    property string tooltipText: ""
    signal activated

    implicitHeight: chip.iconOnly
      ? Style.spacing.controlHeight
      : Math.max(
          Style.spacing.controlHeight,
          chipLabel.implicitHeight + Style.spacing.controlPaddingY * 2
        )
    implicitWidth: chip.iconOnly
      ? implicitHeight + Style.spacing.controlPaddingX
      : chipLabel.implicitWidth + Style.spacing.controlPaddingX * 2
    radius: height / 2
    color: chip.active ? Color.accent : panel.subtleSurface
    border.width: Style.spacing.hairline
    border.color: chip.danger ? Color.urgent : (chip.active ? Color.accent : panel.hairline)

    Text {
      id: chipLabel

      anchors.centerIn: parent
      text: chip.label
      textFormat: Text.PlainText
      font.family: Style.font.family
      font.pixelSize: chip.iconOnly ? Style.font.iconLarge : Style.font.bodySmall
      color: chip.active ? Color.background : (chip.danger ? Color.urgent : Color.foreground)
    }

    MouseArea {
      id: chipMouse

      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: chip.activated()
    }

    PanelToolTip {
      visible: chip.tooltipText !== "" && chipMouse.containsMouse
      text: chip.tooltipText
      fontFamily: Style.font.family
    }
  }

  component Fact: Item {
    id: fact

    property string label: ""
    property string value: ""
    property bool actionVisible: false
    property string actionIcon: ""
    property string actionTooltip: ""
    signal actionActivated

    implicitHeight: Math.max(factText.implicitHeight, factAction.visible ? factAction.implicitHeight : 0)

    Column {
      id: factText

      anchors.left: parent.left
      anchors.right: factAction.visible ? factAction.left : parent.right
      anchors.rightMargin: factAction.visible ? Style.spacing.controlGap : 0
      anchors.top: parent.top
      spacing: Style.space(2)

      Text {
        width: factText.width
        text: fact.label
        textFormat: Text.PlainText
        font.pixelSize: Style.font.bodySmall
        color: panel.mutedForeground
        elide: Text.ElideRight
      }

      Text {
        width: factText.width
        text: fact.value
        textFormat: Text.PlainText
        font.pixelSize: Style.font.body
        color: Color.foreground
        elide: Text.ElideRight
      }
    }

    Chip {
      id: factAction

      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      visible: fact.actionVisible
      label: fact.actionIcon
      iconOnly: true
      tooltipText: fact.actionTooltip
      onActivated: fact.actionActivated()
    }
  }

  component DetailLine: Item {
    id: detail

    property string label: ""
    property string value: ""

    implicitHeight: Math.max(detailLabel.implicitHeight, detailValue.implicitHeight)

    Text {
      id: detailLabel

      anchors.left: parent.left
      text: detail.label
      textFormat: Text.PlainText
      font.pixelSize: Style.font.bodySmall
      color: panel.mutedForeground
    }

    Text {
      id: detailValue

      anchors.right: parent.right
      anchors.left: detailLabel.right
      anchors.leftMargin: Style.space(12)
      horizontalAlignment: Text.AlignRight
      text: detail.value
      textFormat: Text.PlainText
      font.pixelSize: Style.font.bodySmall
      color: Color.foreground
      elide: Text.ElideRight
    }
  }

  KeyboardPanel {
    id: panelWindow

    anchorItem: panel.anchorItem
    owner: panel.hostWidget
    bar: panel.bar
    open: panel.opened
    focusTarget: keyCatcher
    contentWidth: panelWindow.fittedContentWidth(Style.space(400))
    // Only the visible page may size the popup, so the hidden one cannot
    // stretch the card to a height it does not need. The page Flickables inset
    // their viewport by Style.space(16) on every edge, so the two vertical
    // margins are added back here; otherwise the viewport stays shorter than
    // its content and the page scrolls even when the screen has room.
    contentHeight: panelWindow.fittedContentHeight(
      (panel.page === "settings" ? settingsContent.implicitHeight : content.implicitHeight)
        + Style.space(16) * 2,
      Style.space(980))

    PanelKeyCatcher {
      id: keyCatcher

      anchors.fill: parent
      focus: true

      Keys.onPressed: function (event) {
        if (event.key === Qt.Key_Escape) {
          // Escape unwinds one step: settings back to details, details closed.
          if (panel.page === "settings")
            panel.page = "details";
          else
            panel.close();
          event.accepted = true;
        } else if (event.key === Qt.Key_R && panel.page === "details") {
          // Refresh is an operational vehicle action, so it stays on details.
          panel.refresh();
          event.accepted = true;
        }
      }

      Flickable {
        id: panelFlick

        anchors.fill: parent
        anchors.margins: Style.space(16)
        visible: panel.page === "details"
        enabled: panelFlick.visible
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: content

          width: panelFlick.width
          spacing: Style.space(12)

          // Header: identity on the left, refresh and settings on the right.
          Item {
            width: content.width
            implicitHeight: Math.max(headerText.implicitHeight, headerActions.implicitHeight)

            Column {
              id: headerText

              anchors.left: parent.left
              anchors.right: headerActions.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                width: headerText.width
                text: panel.hasData ? Model.vehicleTitle(panel.vehicle) : "OmaRivian"
                textFormat: Text.PlainText
                font.pixelSize: Style.font.title
                font.weight: Font.Medium
                color: Color.foreground
                elide: Text.ElideRight
              }

              Text {
                width: headerText.width
                text: Model.headerSubtitle(panel.vehicle)
                textFormat: Text.PlainText
                font.pixelSize: Style.font.bodySmall
                color: panel.mutedForeground
                elide: Text.ElideRight
              }

              // What the vehicle is actually doing, in the theme-safe tone for
              // that state. The word carries the meaning on its own; color and
              // the dot only reinforce it, so the line survives a color-blind
              // reading and a monochrome theme.
              Item {
                id: activityRow

                width: headerText.width
                visible: panel.hasData && activityLabel.text !== ""
                implicitHeight: activityLabel.implicitHeight

                Rectangle {
                  id: activityDot

                  width: Style.space(6)
                  height: width
                  radius: width / 2
                  anchors.left: parent.left
                  anchors.verticalCenter: activityLabel.verticalCenter
                  color: panel.activityTone(panel.activity.tone)

                  // Charging is the one state that keeps changing while you
                  // look at it. A 1.8 s cycle is far below any flash threshold,
                  // and it only runs while the popup is actually on screen.
                  SequentialAnimation on opacity {
                    id: activityPulse

                    running: panel.activity.pulse && panel.opened
                    loops: Animation.Infinite

                    NumberAnimation {
                      from: 1
                      to: 0.3
                      duration: 900
                      easing.type: Easing.InOutQuad
                    }

                    NumberAnimation {
                      from: 0.3
                      to: 1
                      duration: 900
                      easing.type: Easing.InOutQuad
                    }

                    // A stopped value source holds its last frame, so hand the
                    // dot back at full strength when the pulse ends.
                    onRunningChanged: {
                      if (!activityPulse.running)
                        activityDot.opacity = 1;
                    }
                  }
                }

                Text {
                  id: activityLabel

                  anchors.left: activityDot.right
                  anchors.leftMargin: Style.space(6)
                  anchors.top: parent.top
                  text: panel.hasData ? panel.activity.label : ""
                  textFormat: Text.PlainText
                  font.pixelSize: Style.font.body
                  font.weight: Font.Medium
                  color: panel.activityTone(panel.activity.tone)
                }

                // Time to the configured charge limit, and only while charging.
                // This is the single place the estimate appears.
                Text {
                  id: activityEta

                  readonly property string eta: panel.hasData ? Model.chargeEtaLabel(panel.vehicle) : ""

                  anchors.left: activityLabel.right
                  anchors.leftMargin: Style.space(6)
                  anchors.right: parent.right
                  anchors.baseline: activityLabel.baseline
                  visible: activityEta.eta !== ""
                  text: activityEta.eta === "" ? "" : "· " + activityEta.eta
                  textFormat: Text.PlainText
                  font.pixelSize: Style.font.bodySmall
                  color: panel.mutedForeground
                  elide: Text.ElideRight
                }
              }

              Text {
                width: headerText.width
                visible: panel.hasData && (panel.kind !== "ok" || panel.stale || panel.helperError !== "")
                text: Model.cachedStatusLabel(panel.kind, panel.stateData, panel.vehicle, panel.helperError, panel.nowMs)
                textFormat: Text.PlainText
                font.pixelSize: Style.font.bodySmall
                color: (panel.kind === "auth-expired" || panel.kind === "schema-error" || panel.helperError !== "") ? Color.urgent : panel.mutedForeground
                elide: Text.ElideRight
              }
            }

            Row {
              id: headerActions

              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.spacing.controlGap

              Chip {
                id: refreshChip

                label: panel.busy ? "…" : "Refresh"
                onActivated: panel.refresh()
              }

              // Gear entry point to the settings page. PanelActionButton brings
              // the shell's own hover, focus-ring, and keyboard activation, so
              // the affordance is discoverable without a hidden gesture.
              PanelActionButton {
                anchors.verticalCenter: parent.verticalCenter
                size: refreshChip.implicitHeight
                iconText: ""
                tooltipText: "Settings"
                fontFamily: Style.font.family
                fontSize: Style.font.icon
                bordered: true
                focusable: true
                onClicked: panel.page = "settings"
              }
            }
          }

          // Keep the full status surface for empty/error states. Cached-data
          // context lives in the identity header above when vehicle data exists.
          Rectangle {
            width: content.width
            visible: !panel.hasData && (panel.kind !== "ok" || panel.helperError !== "")
            implicitHeight: bannerCol.implicitHeight + Style.space(24)
            radius: Style.cornerRadius
            color: panel.subtleSurface
            border.width: Style.spacing.hairline
            border.color: (panel.kind === "auth-expired" || panel.kind === "schema-error" || panel.helperError !== "") ? Color.urgent : panel.hairline

            Column {
              id: bannerCol

              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(12)
              spacing: Style.space(2)

              Text {
                width: bannerCol.width
                text: panel.helperError !== "" ? "Helper failed" : Model.statusBanner(panel.kind, panel.stateData).title
                textFormat: Text.PlainText
                font.pixelSize: Style.font.body
                font.weight: Font.Medium
                color: Color.foreground
                visible: text !== ""
                elide: Text.ElideRight
              }

              Text {
                width: bannerCol.width
                text: panel.helperError !== "" ? panel.helperError : Model.statusBanner(panel.kind, panel.stateData).detail
                textFormat: Text.PlainText
                font.pixelSize: Style.font.bodySmall
                color: panel.mutedForeground
                wrapMode: Text.WordWrap
                visible: text !== ""
              }
            }
          }

          // Vehicle switcher, only when the account has more than one.
          Row {
            width: content.width
            visible: panel.shownState.vehicles.length > 1
            spacing: Style.space(8)

            Repeater {
              model: panel.shownState.vehicles

              Chip {
                required property var modelData

                label: modelData.name
                active: panel.vehicle && modelData.id === panel.vehicle.id
                enabled: !panel.busy
                opacity: enabled ? 1 : 0.6
                onActivated: panel.selectVehicleId(modelData.id)
              }
            }
          }

          // Vehicle artwork hero. The provider render is a wide, mostly transparent
          // canvas, so scale it until the car's own bounding box spans the panel and
          // let this frame clip away the surrounding padding.
          Item {
            id: hero

            // Fractions of the source render that hold the car, plus a little margin.
            readonly property real cropX: 0.0648
            readonly property real cropY: 0.2825
            readonly property real cropWidth: 0.8241
            readonly property real cropHeight: 0.4873
            // Only bites if a render arrives with an unexpected shape; it keeps a tall
            // image from stretching the panel instead of cropping into the car.
            readonly property real maxHeight: Style.space(160)
            readonly property real cropAspect: (heroArt.implicitWidth > 0 && heroArt.implicitHeight > 0) ? (hero.cropWidth * heroArt.implicitWidth) / (hero.cropHeight * heroArt.implicitHeight) : 0
            readonly property real viewWidth: hero.cropAspect > 0 ? Math.min(hero.width, hero.maxHeight * hero.cropAspect) : 0
            readonly property real viewHeight: hero.cropAspect > 0 ? hero.viewWidth / hero.cropAspect : 0

            width: content.width
            // A missing, null, or unreadable render collapses the row entirely.
            visible: panel.hasData && panel.artworkUrl !== "" && heroArt.status === Image.Ready
            implicitHeight: Math.round(hero.viewHeight)
            clip: true

            Image {
              id: heroArt

              source: panel.artworkUrl
              asynchronous: true
              cache: true
              smooth: true
              mipmap: true
              fillMode: Image.PreserveAspectFit
              width: hero.viewWidth / hero.cropWidth
              height: hero.viewHeight / hero.cropHeight
              x: Math.round((hero.width - hero.viewWidth) / 2 - hero.cropX * heroArt.width)
              y: Math.round(-hero.cropY * heroArt.height)
            }
          }

          // Battery headline: charge, range, and the charge-limit marker.
          Column {
            width: content.width
            visible: panel.hasData
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: Math.max(socText.implicitHeight, rangeText.implicitHeight)

              Text {
                id: socText

                anchors.left: parent.left
                anchors.baseline: rangeText.baseline
                text: Model.formatPercent(panel.hasData ? panel.vehicle.battery.percent : null)
                textFormat: Text.PlainText
                font.pixelSize: Style.font.display
                font.weight: Font.DemiBold
                color: Color.accent
              }

              Text {
                id: rangeText

                anchors.right: parent.right
                anchors.bottom: parent.bottom
                text: Model.formatDistance(panel.hasData ? panel.vehicle.battery.rangeKm : null, panel.useImperial)
                textFormat: Text.PlainText
                font.pixelSize: Style.font.title
                color: Color.foreground
              }
            }

            Rectangle {
              width: parent.width
              height: Style.space(8)
              radius: height / 2
              color: panel.subtleSurface

              Rectangle {
                height: parent.height
                radius: parent.radius
                width: parent.width * Math.max(0, Math.min(1, (panel.hasData && panel.vehicle.battery.percent !== null ? panel.vehicle.battery.percent : 0) / 100))
                color: Color.accent
                opacity: panel.hasData && panel.vehicle.charging.charging ? 1 : 0.75
              }

              Rectangle {
                visible: panel.hasData && panel.vehicle.battery.limitPercent !== null
                width: Style.space(2)
                height: parent.height + Style.space(4)
                y: -Style.space(2)
                x: parent.width * Math.max(0, Math.min(1, (panel.hasData && panel.vehicle.battery.limitPercent !== null ? panel.vehicle.battery.limitPercent : 0) / 100)) - width / 2
                color: Color.foreground
              }
            }

            // Names the limit the marker above draws, and nothing else: the
            // activity row already says charging and how long is left.
            Text {
              width: parent.width
              visible: text !== ""
              text: Model.chargeCaption(panel.vehicle)
              textFormat: Text.PlainText
              font.pixelSize: Style.font.bodySmall
              color: panel.mutedForeground
              elide: Text.ElideRight
            }
          }

          // At-a-glance facts, two per row.
          Grid {
            id: factGrid

            width: content.width
            visible: panel.hasData
            columns: 2
            columnSpacing: Style.space(12)
            rowSpacing: Style.space(12)

            Repeater {
              model: Model.factRows(panel.vehicle, {
                imperial: panel.useImperial,
                locationEnabled: panel.locationEnabled
              })

              Fact {
                required property var modelData

                width: (factGrid.width - factGrid.columnSpacing) / 2
                label: modelData.label
                value: modelData.value
                actionVisible: modelData.label === "Location" && panel.locationEnabled && panel.hasData && panel.vehicle.location !== null
                actionIcon: "\uf279"
                actionTooltip: "Open in maps"
                onActionActivated: Qt.openUrlExternally(Model.mapsUrl(panel.vehicle))
              }
            }
          }

          Rectangle {
            width: content.width
            height: Style.spacing.hairline
            color: panel.hairline
            visible: panel.hasData
          }

          Column {
            width: content.width
            visible: panel.hasData
            spacing: Style.space(4)

            Repeater {
              model: Model.detailRows(panel.vehicle, {
                imperial: panel.useImperial,
                nowMs: panel.nowMs,
                polledAt: panel.shownState.polledAt
              })

              DetailLine {
                required property var modelData

                width: content.width
                label: modelData.label
                value: modelData.value
              }
            }
          }

          Text {
            width: content.width
            visible: !panel.hasData
            text: panel.kind === "unlinked" ? "Link your Rivian account to see battery, charging, security, climate, and location at a glance. OmaRivian is read-only and never sends commands to the vehicle." : "No vehicle data to show yet."
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.pixelSize: Style.font.body
            color: panel.mutedForeground
          }

          // Bottom padding so the fitted content height leaves a margin.
          Item {
            width: 1
            height: Style.space(4)
          }
        }
      }

      // Settings page. It is a sibling of the detail view rather than a
      // section inside it, so preferences scroll on their own and never
      // change how tall the vehicle view has to be.
      Flickable {
        id: settingsFlick

        anchors.fill: parent
        anchors.margins: Style.space(16)
        visible: panel.page === "settings"
        enabled: settingsFlick.visible
        contentWidth: width
        contentHeight: settingsContent.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: settingsContent

          width: settingsFlick.width
          spacing: Style.space(12)

          // Header: where you are, and the way back to the vehicle.
          Item {
            width: settingsContent.width
            implicitHeight: Math.max(settingsTitle.implicitHeight, doneChip.implicitHeight)

            Text {
              id: settingsTitle

              anchors.left: parent.left
              anchors.right: doneChip.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              text: "OmaRivian Settings"
              textFormat: Text.PlainText
              font.pixelSize: Style.font.title
              font.weight: Font.Medium
              color: Color.foreground
              elide: Text.ElideRight
            }

            Chip {
              id: doneChip

              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              label: "Done"
              tooltipText: "Back to vehicle (Esc)"
              onActivated: panel.page = "details"
            }
          }

          Rectangle {
            width: settingsContent.width
            height: Style.spacing.hairline
            color: panel.hairline
          }

          Column {
            width: settingsContent.width
            spacing: Style.space(8)

            Text {
              text: "Appearance"
              textFormat: Text.PlainText
              font.pixelSize: Style.font.bodySmall
              font.weight: Font.Medium
              color: panel.mutedForeground
            }

            Toggle {
              width: settingsContent.width
              label: "Show percentage in bar"
              checked: panel.showChargeInBar
              foreground: Color.foreground
              accent: Color.accent
              fontFamily: Style.font.family
              onClicked: panel.setShowChargeInBar(!panel.showChargeInBar)
            }
          }

          Rectangle {
            width: settingsContent.width
            height: Style.spacing.hairline
            color: panel.hairline
          }

          Column {
            width: settingsContent.width
            spacing: Style.space(8)

            Text {
              text: "Privacy"
              textFormat: Text.PlainText
              font.pixelSize: Style.font.bodySmall
              font.weight: Font.Medium
              color: panel.mutedForeground
            }

            // Flipping this refreshes the vehicle, so the row stays inert
            // while the helper runs rather than queueing conflicting states.
            Toggle {
              width: settingsContent.width
              label: "Vehicle location"
              description: "Saves current coordinates on this device. Shared with OpenStreetMap only when you open a map."
              checked: panel.locationEnabled
              foreground: Color.foreground
              accent: Color.accent
              fontFamily: Style.font.family
              enabled: !panel.busy
              opacity: enabled ? 1 : 0.6
              onClicked: panel.setLocationEnabled(!panel.locationEnabled)
            }
          }

          Rectangle {
            width: settingsContent.width
            height: Style.spacing.hairline
            color: panel.hairline
          }

          Column {
            width: settingsContent.width
            spacing: Style.space(8)

            Text {
              text: "Account"
              textFormat: Text.PlainText
              font.pixelSize: Style.font.bodySmall
              font.weight: Font.Medium
              color: panel.mutedForeground
            }

            // Account actions, with unlink behind a confirmation step.
            Item {
              width: settingsContent.width
              implicitHeight: linkChip.implicitHeight

              Chip {
                id: linkChip

                anchors.left: parent.left
                label: panel.kind === "unlinked" ? "Link account" : "Re-link"
                onActivated: panel.link()
              }

              Row {
                anchors.right: parent.right
                spacing: Style.space(8)

                Chip {
                  visible: !panel.confirmUnlink && panel.kind !== "unlinked"
                  enabled: !panel.busy
                  opacity: enabled ? 1 : 0.6
                  label: "Unlink"
                  onActivated: panel.confirmUnlink = true
                }

                Chip {
                  visible: panel.confirmUnlink
                  label: "Cancel"
                  onActivated: panel.confirmUnlink = false
                }

                Chip {
                  visible: panel.confirmUnlink
                  enabled: !panel.busy
                  opacity: enabled ? 1 : 0.6
                  danger: true
                  label: "Confirm unlink"
                  onActivated: panel.unlink()
                }
              }
            }
          }

          Text {
            width: settingsContent.width
            visible: panel.pluginVersion !== ""
            text: visible ? "OmaRivian v" + panel.pluginVersion : ""
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: Style.font.caption
            color: panel.mutedForeground
          }

          // Bottom padding so the fitted content height leaves a margin.
          Item {
            width: 1
            height: Style.space(4)
          }
        }
      }
    }
  }
}
