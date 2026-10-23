import tkinter as tk
import unittest
from popup_placement import install,centered_geometry

class PopupPlacement(unittest.TestCase):
    def test_geometry_stays_visible(self):
        self.assertEqual(centered_geometry(800,420,1920,1080),'800x420+560+330')
        self.assertEqual(centered_geometry(2000,1200,1920,1080),'2000x1200+0+0')

    def test_new_custom_popups_center_without_moving_main_window(self):
        root=tk.Tk();root.geometry('500x400+30+40');install(root)
        try:
            root.update();before=(root.winfo_x(),root.winfo_y())
            window=tk.Toplevel(root);window.geometry('400x200+5+5');window.update();root.update_idletasks()
            self.assertEqual(window.winfo_x(),(window.winfo_screenwidth()-400)//2)
            # Windows adds a titlebar border to winfo_y; check the actual requested geometry.
            self.assertIn('+'+str((window.winfo_screenwidth()-400)//2)+'+',window.geometry())
            self.assertEqual((root.winfo_x(),root.winfo_y()),before)
            if hasattr(root,'_popup_native_hook'):self.assertTrue(root._popup_native_hook[0])
            window.destroy()
        finally:root.destroy()

if __name__=='__main__':unittest.main()
