"""Isolated Airy GUI entry. The frozen three-mode __main__ stays byte-identical."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from .circular_gui import AiryMainWindow

def main():
    app=QApplication(sys.argv)
    app.setApplicationName('光纹 LightFringe')
    app.setFont(QFont('Microsoft YaHei UI',10))
    app.setStyle('Fusion')
    window=AiryMainWindow()
    window.show()
    return app.exec()

if __name__=='__main__':raise SystemExit(main())
