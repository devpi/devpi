
import sys
import yappi
from devpi_server.main import main

yappi.start()
try:
    sys.exit(main())
finally:
    stats = yappi.get_func_stats()
    stats.print_all()
    import pdb ; pdb.set_trace()

