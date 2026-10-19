from tkinter import ttk

class InlinePanel(ttk.Frame):
    """Notebook page with navigation shared by catalogue and batch browsers."""
    def __init__(self,app,title):
        super().__init__(app.pages)
        self.app=app;app.pages.add(self,text=title);app.pages.select(self)
    def lift(self):self.app.pages.select(self)
    def destroy(self):
        self.app.pages.forget(self)
        super().destroy()
