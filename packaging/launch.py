# Punto di ingresso per PyInstaller (un modulo __main__ dentro il pacchetto
# perderebbe gli import relativi).
import sys

from openwisp_voucher.__main__ import main

sys.exit(main())
