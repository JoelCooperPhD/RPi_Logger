# Support functions for a factory format of WBUS-EMMC

FAT = """000001b0 00 00 00 00 00 00 00 00 98 96 af 9c 00 00 00 21 |...............!|
000001c0 03 00 06 17 ea fd 00 08 00 00 00 f8 71 00 00 00 |............q...|
000001f0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 55 aa |..............U.|
00100000 eb 58 90 6d 6b 66 73 2e 66 61 74 00 02 08 20 00 |.X.mkfs.fat... .|
00100010 02 00 00 00 00 f8 00 00 3e 00 76 00 00 08 00 00 |........>.v.....|
00100020 00 f8 71 00 70 1c 00 00 00 00 00 00 02 00 00 00 |..q.p...........|
00100030 01 00 06 00 00 00 00 00 00 00 00 00 00 00 00 00 |................|
00100040 80 00 29 88 8c 78 e6 50 59 42 4d 4d 43 20 20 20 |..)..x.PYBMMC   |
00100050 20 20 46 41 54 33 32 20 20 20 0e 1f be 77 7c ac |  FAT32   ...w|.|
00100060 22 c0 74 0b 56 b4 0e bb 07 00 cd 10 5e eb f0 32 |".t.V.......^..2|
00100070 e4 cd 16 cd 19 eb fe 54 68 69 73 20 69 73 20 6e |.......This is n|
00100080 6f 74 20 61 20 62 6f 6f 74 61 62 6c 65 20 64 69 |ot a bootable di|
00100090 73 6b 2e 20 20 50 6c 65 61 73 65 20 69 6e 73 65 |sk.  Please inse|
001000a0 72 74 20 61 20 62 6f 6f 74 61 62 6c 65 20 66 6c |rt a bootable fl|
001000b0 6f 70 70 79 20 61 6e 64 0d 0a 70 72 65 73 73 20 |oppy and..press |
001000c0 61 6e 79 20 6b 65 79 20 74 6f 20 74 72 79 20 61 |any key to try a|
001000d0 67 61 69 6e 20 2e 2e 2e 20 0d 0a 00 00 00 00 00 |gain ... .......|
001001f0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 55 aa |..............U.|
00100200 52 52 61 41 00 00 00 00 00 00 00 00 00 00 00 00 |RRaA............|
001003e0 00 00 00 00 72 72 41 61 df 37 0e 00 02 00 00 00 |....rrAa.7......|
001003f0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 55 aa |..............U.|
00100c00 eb 58 90 6d 6b 66 73 2e 66 61 74 00 02 08 20 00 |.X.mkfs.fat... .|
00100c10 02 00 00 00 00 f8 00 00 3e 00 76 00 00 08 00 00 |........>.v.....|
00100c20 00 f8 71 00 70 1c 00 00 00 00 00 00 02 00 00 00 |..q.p...........|
00100c30 01 00 06 00 00 00 00 00 00 00 00 00 00 00 00 00 |................|
00100c40 80 00 29 88 8c 78 e6 50 59 42 4d 4d 43 20 20 20 |..)..x.PYBMMC   |
00100c50 20 20 46 41 54 33 32 20 20 20 0e 1f be 77 7c ac |  FAT32   ...w|.|
00100c60 22 c0 74 0b 56 b4 0e bb 07 00 cd 10 5e eb f0 32 |".t.V.......^..2|
00100c70 e4 cd 16 cd 19 eb fe 54 68 69 73 20 69 73 20 6e |.......This is n|
00100c80 6f 74 20 61 20 62 6f 6f 74 61 62 6c 65 20 64 69 |ot a bootable di|
00100c90 73 6b 2e 20 20 50 6c 65 61 73 65 20 69 6e 73 65 |sk.  Please inse|
00100ca0 72 74 20 61 20 62 6f 6f 74 61 62 6c 65 20 66 6c |rt a bootable fl|
00100cb0 6f 70 70 79 20 61 6e 64 0d 0a 70 72 65 73 73 20 |oppy and..press |
00100cc0 61 6e 79 20 6b 65 79 20 74 6f 20 74 72 79 20 61 |any key to try a|
00100cd0 67 61 69 6e 20 2e 2e 2e 20 0d 0a 00 00 00 00 00 |gain ... .......|
00100df0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 55 aa |..............U.|
00104000 f8 ff ff 0f ff ff ff 0f f8 ff ff 0f 00 00 00 00 |................|
00492000 f8 ff ff 0f ff ff ff 0f f8 ff ff 0f 00 00 00 00 |................|
"""

def _mkfs(bdev, fat):
    lar = fat.split('\n')
    cbla = -1
    for x in lar:
        xar = x.split(' ')
        if len(xar) >= 17:
            a = int(xar[0], 16)
            bla = a >> 9
            offset = a & 0x1ff
            if bla != cbla:
                if cbla >= 0:
                    bdev.writeblocks(cbla, ba)
                    print('%x' % (cbla*512))
                ba = bytearray(512)
                cbla = bla
            print(x)
            print(end='%08X' % (a))
            for i in range(16):
                ba[offset+i] = int(xar[1+i], 16)
                print(end=' %02X' % (ba[offset+i]))
            print()
    for x in ba:
        if x:
            bdev.writeblocks(cbla, ba)
            print('%x' % (cbla*512))
            break

def mmc_format():
    import pyb
    mmc = pyb.MMCard()
    mmc.power(1)
    print('Formatting...')
    _mkfs(mmc, FAT)
    print('Done')

print('Run mmc_format() to format the WBUS-EMMC flash memory')
