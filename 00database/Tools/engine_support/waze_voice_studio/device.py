"""ADB access to the observed Waze recorder, using labels and resource IDs."""
from __future__ import annotations

import re
import subprocess
import time
import unicodedata
import xml.etree.ElementTree as ET

PREFIX = "com.waze:id/"


def normalized(text):
    text = unicodedata.normalize("NFKD", text).lower()
    text = text.replace("okay", "ok")
    return re.sub(r"[^a-z0-9]", "", text)


def by_id(root, name):
    return root.find(f".//node[@resource-id='{PREFIX}{name}']")


def bounds(node):
    return tuple(map(int, re.findall(r"-?\d+", node.attrib["bounds"])))


def text_of(root, name):
    node = by_id(root, name)
    return node.get("text", "") if node is not None else ""


def rows(root):
    result = []
    for container in root.findall(f".//node[@resource-id='{PREFIX}promptContainer']"):
        label = by_id(container, "lblItemName")
        limit = text_of(container, "lblMaxDuration")
        match = re.search(r"([\d.]+)\s+seconds?", limit)
        if label is not None and label.get("text") and match:
            result.append({
                "label": label.get("text"), "max_seconds": float(match[1]),
                "recorded": by_id(container, "btnDeleteItem") is not None,
                "node": label, "container": container,
            })
    return result


class WazeDevice:
    def __init__(self, serial=None, emit=print):
        self.emit = emit
        listing = subprocess.run(["adb", "devices"], capture_output=True, text=True,
                                 check=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        online = [line.split()[0] for line in listing.splitlines()[1:]
                  if len(line.split()) >= 2 and line.split()[1] == "device"]
        if serial and serial not in online:
            raise RuntimeError(f"Phone {serial} is not authorized/connected.")
        if not serial and len(online) != 1:
            raise RuntimeError("Connect and authorize one Android phone with USB debugging.")
        self.serial = serial or online[0]

    def adb(self, *args, timeout=15):
        result = subprocess.run(["adb", "-s", self.serial, *map(str, args)],
                                capture_output=True, check=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.decode("utf-8", errors="replace")

    def snapshot(self):
        self.adb("shell", "uiautomator", "dump", "/sdcard/waze_studio_ui.xml")
        value = self.adb("exec-out", "cat", "/sdcard/waze_studio_ui.xml")
        root = ET.fromstring(value[value.index("<?xml"):])
        if by_id(root, "promptsRecycler") is None:
            raise RuntimeError("On the phone, open Waze's Voice recorder for the intended voice.")
        return root

    def require_list(self, root):
        if by_id(root, "btnRecord") is not None:
            raise RuntimeError("A recording review is open. Save or cancel it on the phone first.")

    def tap(self, node):
        left, top, right, bottom = bounds(node)
        if right <= left or bottom <= top:
            raise RuntimeError("The target control is not visible.")
        self.adb("shell", "input", "tap", (left + right)//2, (top + bottom)//2)

    def tap_id(self, root, name):
        node = by_id(root, name)
        if node is None:
            raise RuntimeError(f"Waze control {name} is missing; stopped without guessing.")
        self.tap(node)

    def scroll(self, root, down=True):
        self.require_list(root)
        left, top, right, bottom = bounds(by_id(root, "promptsRecycler"))
        nav = root.find(".//node[@resource-id='android:id/navigationBarBackground']")
        if nav is not None:
            bottom = min(bottom, bounds(nav)[1])
        height = bottom - top
        x = (left + right)//2
        high, low = int(top + .27*height), int(top + .68*height)
        start, end = (low, high) if down else (high, low)
        self.adb("shell", "input", "swipe", x, start, x, end, 850)
        time.sleep(.3)

    def signature(self, root):
        return tuple((r["label"], bounds(r["node"])) for r in rows(root))

    def top(self):
        root = self.snapshot()
        self.require_list(root)
        unchanged = 0
        for _ in range(40):
            before = self.signature(root)
            self.scroll(root, down=False)
            root = self.snapshot()
            unchanged = unchanged + 1 if self.signature(root) == before else 0
            if unchanged >= 2:
                return root
        raise RuntimeError("Could not reach the top of Waze's recorder list.")

    def inventory(self):
        root = self.top()
        found = {}
        section = ""
        unchanged = 0
        for _ in range(50):
            recycler = by_id(root, "promptsRecycler")
            for child in recycler:
                heading = text_of(child, "settingsTitleText")
                if heading:
                    section = heading
                for row in rows(child):
                    key = normalized(row["label"])
                    item = {k: row[k] for k in ("label", "max_seconds", "recorded")}
                    item["section"] = section
                    if key not in found:
                        self.emit(f"  {len(found)+1:02d}  {item['section']} / {item['label']}"
                                  f"  [{'recorded' if item['recorded'] else 'empty'}]")
                        found[key] = item
                    else:
                        # A partially clipped row may have hidden its delete button.
                        found[key]["recorded"] |= item["recorded"]
            if unchanged >= 2:
                self.emit(f"Inventory complete: {len(found)} slots.")
                return list(found.values())
            before = self.signature(root)
            self.scroll(root)
            root = self.snapshot()
            unchanged = unchanged + 1 if self.signature(root) == before else 0
        raise RuntimeError("Recorder inventory did not reach the bottom; no run started.")

    def find(self, label):
        wanted = normalized(label)
        root = self.snapshot()
        self.require_list(root)
        reset = False
        unchanged = 0
        for _ in range(65):
            for row in rows(root):
                if normalized(row["label"]) == wanted:
                    _, t, _, b = bounds(row["node"])
                    _, top, _, bottom = bounds(by_id(root, "promptsRecycler"))
                    nav = root.find(".//node[@resource-id='android:id/navigationBarBackground']")
                    if nav is not None:
                        bottom = min(bottom, bounds(nav)[1])
                    # Never tap a row clipped by the header/navigation bar.
                    if t > top + 20 and b < bottom - 20:
                        return root, row
            before = self.signature(root)
            self.scroll(root)
            root = self.snapshot()
            unchanged = unchanged + 1 if self.signature(root) == before else 0
            if unchanged >= 2:
                if reset:
                    break
                root = self.top()
                reset, unchanged = True, 0
        raise RuntimeError(f"Could not find a fully visible Waze slot: {label}")

    def inspect_dialog(self, label):
        root, row = self.find(label)
        self.tap(row["node"])
        dialog = self.snapshot()
        actual = text_of(dialog, "lblInstructionName")
        if normalized(actual) != normalized(label):
            raise RuntimeError(f"Unexpected dialog: {actual!r}; expected {label!r}.")
        for name in ("btnRecord", "btnCancel", "btnSave", "btnPreview", "lblDuration"):
            if by_id(dialog, name) is None:
                raise RuntimeError(f"Missing recorder control: {name}")
        return dialog


if __name__ == "__main__":
    import json
    from pathlib import Path
    device = WazeDevice()
    inventory = device.inventory()
    Path(__file__).with_name("phone_inventory.json").write_text(
        json.dumps({"serial": device.serial, "slots": inventory}, indent=2), encoding="utf-8")
