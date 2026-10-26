import os
import sys

from cffi import FFI


_LIB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib")

_platforms: dict = {
    "win32": "librequest.dll",
    "darwin": "librequest.dylib",
    "other": "librequest.so"
}


ffi = FFI()
ffi.cdef("""
    struct curl_slist {char* data;
                       struct curl_slist* next;};
    typedef struct {size_t size;
                    long status_code;
                    char*  body;
                    char*  headers;
                    size_t header_size;
                    const char* err_msg;
                    struct curl_slist* cookies;} Response;
    typedef struct {void* file_data;
                    size_t file_size;
                    char* field_name;
                    char* filename;} UploadFile;
    Response *http_request(char *method, char *url, char *post_data,
                    char *cookies, const char *headers_list[],
                    size_t headers_count, char* auth, UploadFile files[], size_t files_count);
    void free_response(Response* r);
""")

lib = ffi.dlopen(os.path.join(_LIB_DIR, _platforms.get(sys.platform, _platforms["other"])))
