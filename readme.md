
# Limitations

This server isn't designed to handle a high number of requests. That's because:
- It uses a simple CGI shell script
- It uses a dedicated USB tuner, you can only tune to one frequency at a time

If you want to serve high numbers of clients you could do so easily by sticking a caching reverse proxy in front. HLS will cope with this nicely.
