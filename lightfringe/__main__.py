import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QIcon
from .airy_pdf_gui import AiryPdfMainWindow

def main():
    app=QApplication(sys.argv);app.setApplicationName('光纹 LightFringe')
    app.setFont(QFont('Microsoft YaHei UI',10));app.setStyle('Fusion')
    icon=QIcon(str(Path(__file__).with_name("assets")/"LightFringe.ico"))
    app.setWindowIcon(icon)
    window=AiryPdfMainWindow()
    window.setWindowIcon(icon)
    window.show()
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
