# boot.py -- run on boot-up
import pyb

pyb.country('US') # ISO 3166-1 Alpha-2 code, eg US, GB, DE, AU
pyb.Pin('EN_3V3').on()
# pyb.usb_mode('VCP+MSC', vid=0xf056, pid=1111, msc=(pyb.MMCard(),)) # act as a serial and a storage device
