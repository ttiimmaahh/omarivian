import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "Model.js" as Model

BarWidget {
  id: root

  moduleName: "io.github.ttiimmaahh.omarivian"

  readonly property var panel: panelLoader.item
  readonly property var stateData: panel ? panel.stateData : null
  readonly property bool horizontal: !root.vertical

  readonly property bool opened: panel ? panel.opened : false
  readonly property bool popoutSwitchClosing: panel ? panel.popoutSwitchClosing : false

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function open() {
    if (panel)
      panel.open();
  }
  function close() {
    if (panel)
      panel.close();
  }
  function toggle() {
    if (panel)
      panel.toggle();
  }
  function closeForPopoutSwitch() {
    if (panel)
      panel.closeForPopoutSwitch();
  }
  function refresh() {
    if (panel)
      panel.refresh();
  }

  WidgetButton {
    id: button

    readonly property string chargeLabel: Model.barLabel(root.stateData, root.settings, root.horizontal)

    anchors.fill: parent
    bar: root.bar
    text: button.chargeLabel
    labelVisible: false
    hasVisualContent: true
    fixedWidth: root.vertical ? -1 : Style.bar.statusSlot + (button.chargeLabel !== "" ? chargeText.implicitWidth + Style.space(4) : 0)
    tooltipText: Model.tooltipText(root.stateData, {
      unit: root.setting("unit", ""),
      localeName: Qt.locale().name
    }, Date.now())

    Image {
      id: brandMark
      width: Style.bar.iconCanvas - Style.space(2)
      height: Style.bar.iconCanvas - Style.space(2)
      anchors.verticalCenter: parent.verticalCenter
      anchors.horizontalCenter: button.chargeLabel === "" ? parent.horizontalCenter : undefined
      anchors.left: button.chargeLabel !== "" ? parent.left : undefined
      anchors.leftMargin: button.chargeLabel !== "" ? Style.space(6) : 0
      source: Qt.resolvedUrl("assets/rivian-mark.svg")
      fillMode: Image.PreserveAspectFit
      smooth: true
      mipmap: true
    }

    Text {
      id: chargeText
      visible: button.chargeLabel !== ""
      anchors.left: brandMark.right
      anchors.leftMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      text: button.chargeLabel
      color: button.foreground
      font.family: button.fontFamily
      font.pixelSize: Style.font.caption
    }

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.refresh();
      else root.toggle();
    }
  }

  // Kept loaded so the state file stays watched and the bar label stays live
  // while the panel itself is closed.
  Loader {
    id: panelLoader

    active: true
    source: Qt.resolvedUrl("Panel.qml")
    onLoaded: {
      item.bar = Qt.binding(() => root.bar);
      item.settings = Qt.binding(() => root.settings);
      item.anchorItem = Qt.binding(() => button);
      item.hostWidget = Qt.binding(() => root);
    }
  }
}
