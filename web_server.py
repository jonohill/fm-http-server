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
    response = web.StreamResponse()
    response.enable_chunked_encoding()
    response.prepare(request)
    async for chunk in tuner.listen():
        await response.write(chunk)
        if request.transport.is_closing():
            break
    await response.write_eof()
    # return web.Response(status=200, content_type=CONTENT_TYPE, body=tuner.listen())    
    return response

app = web.Application()
app.add_routes(routes)
web.run_app(app)
