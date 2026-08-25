import QtQuick
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
  readonly property bool locationEnabled: panel.settings && panel.settings.locationEnabled === true
  readonly property string kind: Model.statusKind(panel.stateData)
  // Fall back to the last good payload so a transient error keeps numbers on screen.
  readonly property var shownState: (panel.kind === "ok" && panel.stateData.vehicles.length > 0) ? panel.stateData : (panel.lastGood || panel.stateData)
  readonly property var vehicle: Model.selectVehicle(panel.shownState, panel.overrideVehicleId)
  readonly property bool hasData: !!panel.vehicle
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

  function refresh() {
    panel.runHelper(["refresh", panel.locationEnabled ? "--location" : "--no-location"]);
  }
  function selectVehicleId(id) {
    panel.overrideVehicleId = id;
    panel.runHelper(["select", id]);
  }
  function unlink() {
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
    if (Model.statusKind(parsed) === "ok" && parsed.vehicles.length > 0) {
      panel.lastGood = parsed;
      panel.artworkById = panel.artworkFromText(body);
    }
    panel.nowMs = Date.now();
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

  onOpenedChanged: {
    if (!panel.opened)
      return;
    panel.confirmUnlink = false;
    panel.nowMs = Date.now();
    panel.refresh();
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
    signal activated

    implicitHeight: Math.round(Style.font.body * 2.2)
    implicitWidth: chipLabel.implicitWidth + Style.space(24)
    radius: height / 2
    color: chip.active ? Color.accent : panel.subtleSurface
    border.width: 1
    border.color: chip.danger ? Color.urgent : (chip.active ? Color.accent : panel.hairline)

    Text {
      id: chipLabel

      anchors.centerIn: parent
      text: chip.label
      font.pixelSize: Style.font.bodySmall
      color: chip.active ? Color.background : (chip.danger ? Color.urgent : Color.foreground)
    }

    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: chip.activated()
    }
  }

  component Fact: Column {
    id: fact

    property string label: ""
    property string value: ""

    spacing: Style.space(2)

    Text {
      width: fact.width
      text: fact.label
      font.pixelSize: Style.font.bodySmall
      color: panel.mutedForeground
      elide: Text.ElideRight
    }

    Text {
      width: fact.width
      text: fact.value
      font.pixelSize: Style.font.body
      color: Color.foreground
      elide: Text.ElideRight
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
    contentHeight: panelWindow.fittedContentHeight(content.implicitHeight, Style.space(620))

    PanelKeyCatcher {
      id: keyCatcher

      anchors.fill: parent
      focus: true

      Keys.onPressed: function (event) {
        if (event.key === Qt.Key_Escape) {
          panel.close();
          event.accepted = true;
        } else if (event.key === Qt.Key_R) {
          panel.refresh();
          event.accepted = true;
        }
      }

      Column {
        id: content

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Style.space(16)
        spacing: Style.space(12)

        // Header: identity on the left, refresh on the right.
        Item {
          width: content.width
          implicitHeight: Math.max(headerText.implicitHeight, refreshChip.implicitHeight)

          Column {
            id: headerText

            anchors.left: parent.left
            anchors.right: refreshChip.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              width: headerText.width
              text: panel.hasData ? Model.vehicleTitle(panel.vehicle) : "OmaRivian"
              font.pixelSize: Style.font.title
              font.weight: Font.Medium
              color: Color.foreground
              elide: Text.ElideRight
            }

            Text {
              width: headerText.width
              text: panel.hasData ? [Model.vehicleSubtitle(panel.vehicle), Model.connectionLabel(panel.vehicle)].filter(p => p).join(" · ") : "Rivian vehicle status"
              font.pixelSize: Style.font.bodySmall
              color: panel.mutedForeground
              elide: Text.ElideRight
            }
          }

          Chip {
            id: refreshChip

            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            label: panel.busy ? "…" : "Refresh"
            onActivated: panel.refresh()
          }
        }

        // Status / staleness banner; any preserved data stays visible below it.
        Rectangle {
          width: content.width
          visible: panel.kind !== "ok" || panel.stale || panel.helperError !== ""
          implicitHeight: bannerCol.implicitHeight + Style.space(24)
          radius: Style.cornerRadius
          color: panel.subtleSurface
          border.width: 1
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
              font.pixelSize: Style.font.body
              font.weight: Font.Medium
              color: Color.foreground
              visible: text !== ""
              elide: Text.ElideRight
            }

            Text {
              width: bannerCol.width
              text: panel.helperError !== "" ? panel.helperError : Model.statusBanner(panel.kind, panel.stateData).detail
              font.pixelSize: Style.font.bodySmall
              color: panel.mutedForeground
              wrapMode: Text.WordWrap
              visible: text !== ""
            }

            Text {
              width: bannerCol.width
              visible: panel.stale && panel.hasData
              text: "Showing last known data from " + Model.formatAge(panel.shownState.polledAt, panel.nowMs) + "."
              font.pixelSize: Style.font.bodySmall
              color: panel.mutedForeground
              wrapMode: Text.WordWrap
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
              font.pixelSize: Style.font.display
              font.weight: Font.DemiBold
              color: Color.accent
            }

            Text {
              id: rangeText

              anchors.right: parent.right
              anchors.bottom: parent.bottom
              text: Model.formatDistance(panel.hasData ? panel.vehicle.battery.rangeKm : null, panel.useImperial)
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
              width: 2
              height: parent.height + 4
              y: -2
              x: parent.width * Math.max(0, Math.min(1, (panel.hasData && panel.vehicle.battery.limitPercent !== null ? panel.vehicle.battery.limitPercent : 0) / 100)) - 1
              color: Color.foreground
            }
          }

          Text {
            width: parent.width
            text: {
              if (!panel.hasData)
                return "";
              const limit = panel.vehicle.battery.limitPercent;
              return [limit === null ? "" : "Limit " + Model.formatPercent(limit), Model.chargingLabel(panel.vehicle)].filter(p => p).join(" · ");
            }
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
            }
          }
        }

        Chip {
          visible: panel.hasData && panel.locationEnabled && panel.vehicle.location !== null
          label: "Open in maps"
          onActivated: Qt.openUrlExternally(Model.mapsUrl(panel.vehicle))
        }

        Rectangle {
          width: content.width
          height: 1
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
          wrapMode: Text.WordWrap
          font.pixelSize: Style.font.body
          color: panel.mutedForeground
        }

        // Account actions, with unlink behind a confirmation step.
        Item {
          width: content.width
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
              danger: true
              label: "Confirm unlink"
              onActivated: panel.unlink()
            }
          }
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
