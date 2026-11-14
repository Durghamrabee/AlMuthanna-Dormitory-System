from pathlib import Path
from threading import Thread
import os
import webbrowser


def run_window(server, data_dir):
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.title("جامعة المثنى — تشغيل الأقسام الداخلية")
    root.geometry("570x390")
    root.minsize(500, 360)
    root.configure(bg="#f2f5f9")
    title = tk.Label(root, text="نظام إدارة الأقسام الداخلية", font=("Tahoma", 18, "bold"), bg="#f2f5f9", fg="#17354f")
    title.pack(pady=(25, 8))
    status = tk.StringVar(value="جارِ تشغيل النظام المحلي…")
    tk.Label(root, textvariable=status, font=("Tahoma", 11), wraplength=510, bg="#f2f5f9").pack(pady=10)
    busy = False

    def set_busy(value):
        nonlocal busy
        busy = value
        for button in buttons:
            button.configure(state="disabled" if value else "normal")

    def open_browser():
        if server.url:
            webbrowser.open(server.url)

    def start():
        try:
            url = server.start()
        except Exception as exc:
            status.set("تعذر التشغيل. " + str(exc))
            messagebox.showerror("تعذر التشغيل", str(exc), parent=root)
        else:
            status.set("النظام يعمل على هذا الجهاز فقط\n" + url)
            webbrowser.open(url)

    def stop():
        if busy:
            return
        if not messagebox.askyesno("إيقاف النظام", "هل تريد إيقاف النظام المحلي وإغلاق نافذة التشغيل؟", parent=root, default="no"):
            return
        set_busy(True)
        def worker():
            try:
                server.stop()
            except Exception as exc:
                root.after(0, lambda text=str(exc): (messagebox.showerror("تعذر الإيقاف", text, parent=root), set_busy(False)))
            else:
                root.after(0, root.destroy)
        Thread(target=worker, daemon=True).start()

    def restore():
        if busy or server.reused:
            if server.reused:
                messagebox.showinfo("نسخة أخرى تعمل", "نفّذ الاستعادة من نافذة التشغيل الأصلية بعد إغلاق الأعمال المفتوحة.", parent=root)
            return
        path = filedialog.askopenfilename(title="اختر نسخة احتياطية موثوقة", filetypes=[("نسخة النظام ZIP", "*.zip")], parent=root)
        if not path or not messagebox.askyesno("تأكيد استعادة البيانات", "سيُوقف النظام مؤقتاً وتُعاد بيانات النسخة المختارة. ستُحفظ نسخة أمان من بياناتك الحالية. هل تريد المتابعة؟", parent=root, default="no"):
            return
        set_busy(True)
        status.set("جارِ التحقق من النسخة وحفظ نسخة أمان واستعادة البيانات…")
        def worker():
            from .recovery import restore_bundle
            try:
                server.stop()
                safety = restore_bundle(path, data_dir)
                url = server.start()
            except Exception as exc:
                root.after(0, lambda text=str(exc): (status.set("تعذرت الاستعادة. بيانات الأمان محفوظة؛ تحقق من الرسالة."), messagebox.showerror("تعذرت الاستعادة", text, parent=root), set_busy(False)))
            else:
                root.after(0, lambda: (status.set("تمت الاستعادة — " + url), messagebox.showinfo("تمت الاستعادة", "حُفظت نسخة الأمان في:\n" + str(safety), parent=root), set_busy(False)))
        Thread(target=worker, daemon=True).start()

    buttons = []
    for text, command in [("فتح النظام في المتصفح", open_browser), ("فتح مجلد البيانات والنسخ", lambda: os.startfile(str(data_dir))),
                          ("استعادة نسخة احتياطية موثوقة", restore), ("إيقاف النظام وإغلاق", stop)]:
        button = tk.Button(root, text=text, command=command, font=("Tahoma", 11), bg="#195e91", fg="white", relief="flat", padx=12, pady=8)
        button.pack(fill="x", padx=48, pady=5)
        buttons.append(button)
    root.protocol("WM_DELETE_WINDOW", stop)
    root.after(150, start)
    root.mainloop()
