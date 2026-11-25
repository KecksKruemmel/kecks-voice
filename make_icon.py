from kecksvoice import cookie_image

cookie_image(256).save("kecksvoice.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("kecksvoice.ico erstellt")
