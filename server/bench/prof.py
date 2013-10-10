
if __name__ == '__main__':
    import cProfile
    import pstats
    import devpi_server.main
    devpi_server.main
    stats = cProfile.run('devpi_server.main.main(["devpi-server"])', 'prof')
    p = pstats.Stats("prof")
    p.strip_dirs()
    p.sort_stats('cumulative')
    print(p.print_stats(50))

