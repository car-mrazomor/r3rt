#include <stdio.h>
#include <curl/curl.h>
#include <string.h>
#include <stdlib.h>


typedef struct {
    size_t size;
    int    status_code;
    char*  body;
    char*  headers;
    size_t header_size;
    const char* err_msg;
    struct curl_slist* cookies;
} Response;


size_t write_data(void *ptr, size_t size, size_t nmemb, Response *data) {
    size_t index = data->size;
    size_t n = (size * nmemb);
    char* tmp;

    data->size += (size * nmemb);

#ifdef DEBUG
    fprintf(stderr, "data at %p size=%ld nmemb=%ld\n", ptr, size, nmemb);
#endif
    tmp = realloc(data->body, data->size + 1); /* +1 for '\0' */

    if(tmp) {
        data->body = tmp;
    } else {
        if(data->body) {
            free(data->body);
            data->body = NULL;
        }
        return 0;
    }

    memcpy((data->body + index), ptr, n);
    data->body[data->size] = '\0';

    return size * nmemb;
}

size_t write_headers(void *ptr, size_t size, size_t nmemb, Response *data) {
    size_t n = size * nmemb;
    char *tmp = realloc(data->headers, data->header_size + n + 1);

    if (!tmp) return 0;

    data->headers = tmp;
    memcpy(data->headers + data->header_size, ptr, n);
    data->header_size += n;
    data->headers[data->header_size] = '\0';

    return n;
}


Response *PUT(char *url, char *post_data, char *cookies, const char *headers_list[], size_t headers_count, char* auth, char* filename, void* file_data, size_t file_size) {
    CURL *curl = NULL;
    CURLcode res = CURLE_OK;
    curl_mime *mime = NULL;
    curl_mimepart *part = NULL;
    struct curl_slist *headers = NULL;
    Response *response = calloc(1, sizeof(*response));

    if (response == NULL)
        return NULL;

    response->body = malloc(1);
    if (response->body == NULL) {
        free(response);
        return NULL;
    }
    response->body[0] = '\0';

    curl = curl_easy_init();
    if (curl == NULL) {
        response->err_msg = "curl_easy_init failed";
        return response;
    }

    for (size_t i = 0; i < headers_count; i++) {
        struct curl_slist *tmp = curl_slist_append(headers, headers_list[i]);

        if (tmp == NULL) {
            response->err_msg = "Failed to allocate header list";
            goto cleanup;
        }
        headers = tmp;
    }
    
    if ((file_data != NULL && file_size>0) && post_data == NULL) {
        mime = curl_mime_init(curl);
        if (mime) {
            part = curl_mime_addpart(mime);
        }
    
        if (!mime || !part) {
            response->err_msg = "Failed to create multipart upload";
            goto cleanup;
        }

        CURLcode rc = curl_mime_name(part, "file");
        if (rc == CURLE_OK) {
            rc = curl_mime_filename(part, filename);
        }
        if (rc == CURLE_OK) {
            rc = curl_mime_data(part, file_data, (curl_off_t)file_size);
        }
        if (rc == CURLE_OK){
            rc = curl_easy_setopt(curl, CURLOPT_MIMEPOST, mime);
        }

        if (rc != CURLE_OK) {
            response->err_msg = curl_easy_strerror(rc);
            goto cleanup;
        }
    }

    if (res == CURLE_OK)
        curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PUT");

    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_URL, url);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_data);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_WRITEDATA, response);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, write_headers);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_HEADERDATA, response);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    if (res == CURLE_OK)
        res = curl_easy_setopt(curl, CURLOPT_COOKIEFILE, "");

    if (auth != NULL) {
        if (res == CURLE_OK)
            res = curl_easy_setopt(curl, CURLOPT_HTTPAUTH, CURLAUTH_ANY);
        if (res == CURLE_OK)
            res = curl_easy_setopt(curl, CURLOPT_USERPWD, auth);
    }

    if (post_data != NULL && (file_data == NULL && file_size<=0)) {
        if (res == CURLE_OK)
            res = curl_easy_setopt(curl, CURLOPT_POSTFIELDS, post_data);
    }

    if (cookies != NULL) {
        if (res == CURLE_OK)
            res = curl_easy_setopt(curl, CURLOPT_COOKIE, cookies);
    }

    if (res == CURLE_OK)
        res = curl_easy_perform(curl);

    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response->status_code);
    curl_easy_getinfo(curl, CURLINFO_COOKIELIST, &response->cookies);

    if (res != CURLE_OK) {
        response->err_msg = curl_easy_strerror(res);
    }

cleanup:
    if (mime) curl_mime_free(mime);
    curl_slist_free_all(headers);
    if (curl)
        curl_easy_cleanup(curl);
    
    return response;
}
