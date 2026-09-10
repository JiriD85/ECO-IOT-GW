"""Serve build-time gzip assets: no compression CPU cost on the Raspberry Pi."""
import mimetypes
from starlette.staticfiles import StaticFiles


def accepts_gzip(header):
    for part in header.lower().split(','):
        name, *parameters = part.strip().split(';')
        if name != 'gzip':
            continue
        quality = 1.0
        try:
            for parameter in parameters:
                if parameter.strip().startswith('q='):
                    quality = float(parameter.strip()[2:])
        except ValueError:
            return False
        return quality > 0
    return False


class CompressedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        headers = dict(scope.get('headers', []))
        if accepts_gzip(headers.get(b'accept-encoding', b'').decode()) and path.endswith(('.js', '.css', '.svg')):
            _, stat = self.lookup_path(path + '.gz')
            if stat:
                response = await super().get_response(path + '.gz', scope)
                response.headers['Content-Encoding'] = 'gzip'
                response.headers['Content-Type'] = mimetypes.guess_type(path)[0] or 'application/octet-stream'
                response.headers['Vary'] = 'Accept-Encoding'
                return response
        response = await super().get_response(path, scope)
        response.headers['Vary'] = 'Accept-Encoding'
        return response
