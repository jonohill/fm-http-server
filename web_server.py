import aiohttp
from aiohttp import web
from tuner import Tuner
import os

FM_KHZ = int(os.environ.get('FM_KHZ', '99000'))
FM_BITRATE = int(os.environ.get('FM_BITRATE', '24000'))

routes = web.RouteTableDef()

CONTENT_TYPE = 'video/MP2T'

tuner = Tuner(FM_KHZ, bitrate=FM_BITRATE)

@routes.get('/radio.ts')
async def get_radio_stream(request):
    return web.Response(status=200, content_type=CONTENT_TYPE, body=tuner.listen())    

app = web.Application()
app.add_routes(routes)
web.run_app(app)
