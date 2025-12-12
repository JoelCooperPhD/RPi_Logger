import machine
import pyb
pyb.freq(216_000_000)
pyb.Pin('EN_3V3').on()
pyb.country('US') # ISO 3166-1 Alpha-2 code, eg US, GB, DE, AU

# pyb.usb_mode('VCP+MSC', vid=0xf057, pid=2222, msc=(pyb.MMCard(),)) # act as a serial and a storage device

