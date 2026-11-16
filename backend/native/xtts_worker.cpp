#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include "aikit_biz_api.h"
#include "aikit_biz_config.h"
#include "aikit_constant.h"

using namespace AIKIT;

static const char *ABILITY = "e2e44feff";

static std::mutex g_mu;
static std::condition_variable g_cv;
static std::vector<char> g_audio;
static bool g_done = false;
static std::string g_error;

static void write_all(const void *data, size_t size) {
    const char *bytes = static_cast<const char *>(data);
    size_t written = 0;
    while (written < size) {
        size_t chunk = fwrite(bytes + written, 1, size - written, stdout);
        if (chunk == 0) {
            exit(1);
        }
        written += chunk;
    }
    fflush(stdout);
}

static void write_error(const std::string &message) {
    uint32_t mark = 0xFFFFFFFFu;
    uint32_t size = static_cast<uint32_t>(message.size());
    write_all(&mark, 4);
    write_all(&size, 4);
    if (size) {
        write_all(message.data(), size);
    }
}

static void write_pcm(const std::vector<char> &pcm) {
    uint32_t size = static_cast<uint32_t>(pcm.size());
    write_all(&size, 4);
    if (size) {
        write_all(pcm.data(), size);
    }
}

static bool read_exact(void *data, size_t size) {
    char *bytes = static_cast<char *>(data);
    size_t got = 0;
    while (got < size) {
        size_t chunk = fread(bytes + got, 1, size - got, stdin);
        if (chunk == 0) {
            return false;
        }
        got += chunk;
    }
    return true;
}

static void OnOutput(AIKIT_HANDLE *, const AIKIT_OutputData *output) {
    if (output == nullptr || output->node == nullptr) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_mu);
    for (auto *node = output->node; node != nullptr; node = node->next) {
        if (node->value != nullptr && node->len > 0) {
            const char *value = static_cast<const char *>(node->value);
            g_audio.insert(g_audio.end(), value, value + node->len);
        }
    }
}

static void OnEvent(AIKIT_HANDLE *, AIKIT_EVENT eventType, const AIKIT_OutputEvent *) {
    if (eventType != AIKIT_Event_End) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_mu);
    g_done = true;
    g_cv.notify_one();
}

static void OnError(AIKIT_HANDLE *, int32_t err, const char *desc) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_error = std::to_string(err);
    if (desc != nullptr && desc[0] != '\0') {
        g_error.append(" ");
        g_error.append(desc);
    }
    g_done = true;
    g_cv.notify_one();
}

static bool synthesize_line(const std::string &text, const char *vcn, int language, std::string &error) {
    {
        std::lock_guard<std::mutex> lock(g_mu);
        g_audio.clear();
        g_done = false;
        g_error.clear();
    }

    AIKIT_ParamBuilder *paramBuilder = AIKIT_ParamBuilder::create();
    paramBuilder->clear();
    paramBuilder->param("vcn", vcn, strlen(vcn));
    paramBuilder->param("vcnModel", vcn, strlen(vcn));
    paramBuilder->param("language", language);
    paramBuilder->param("textEncoding", "UTF-8", strlen("UTF-8"));

    AIKIT_HANDLE *handle = nullptr;
    int ret = AIKIT_Start(ABILITY, AIKIT_Builder::build(paramBuilder), nullptr, &handle);
    if (ret != 0) {
        delete paramBuilder;
        error = "AIKIT_Start:" + std::to_string(ret);
        return false;
    }

    AIKIT_DataBuilder *dataBuilder = AIKIT_DataBuilder::create();
    dataBuilder->clear();
    AiText *aiText = AiText::get("text")->data(text.c_str(), text.length())->once()->valid();
    dataBuilder->payload(aiText);
    ret = AIKIT_Write(handle, AIKIT_Builder::build(dataBuilder));
    if (ret != 0) {
        AIKIT_End(handle);
        delete paramBuilder;
        delete dataBuilder;
        error = "AIKIT_Write:" + std::to_string(ret);
        return false;
    }

    {
        std::unique_lock<std::mutex> lock(g_mu);
        bool finished = g_cv.wait_for(lock, std::chrono::seconds(60), [] { return g_done; });
        if (!finished) {
            error = "XTTS timed out";
        } else if (!g_error.empty()) {
            error = g_error;
        } else if (g_audio.empty() || g_audio.size() % 2 != 0) {
            error = "XTTS returned invalid pcm";
        }
    }

    AIKIT_End(handle);
    delete paramBuilder;
    delete dataBuilder;
    return error.empty();
}

int main() {
    const char *appId = std::getenv("XTTS_APP_ID");
    const char *apiKey = std::getenv("XTTS_API_KEY");
    const char *apiSecret = std::getenv("XTTS_API_SECRET");
    const char *workDir = std::getenv("XTTS_WORK_DIR");
    const char *vcn = std::getenv("XTTS_VCN");
    const char *languageText = std::getenv("XTTS_LANGUAGE");
    if (!appId || !apiKey || !apiSecret || !workDir || !vcn || !languageText) {
        std::cerr << "xtts worker env is incomplete\n";
        return 1;
    }
    int language = std::atoi(languageText);

    AIKIT_Configurator::builder()
        .app()
            .appID(appId)
            .apiKey(apiKey)
            .apiSecret(apiSecret)
            .workDir(workDir)
        .auth()
            .authType(0)
        .log()
            .logLevel(LOG_LVL_ERROR)
            .logMode(LOG_FILE)
            .logPath(workDir);
    int ret = AIKIT_Init();
    if (ret != 0) {
        std::cerr << "AIKIT_Init:" << ret << "\n";
        return 1;
    }
    AIKIT_Callbacks callbacks = {OnOutput, OnEvent, OnError};
    AIKIT_RegisterAbilityCallback(ABILITY, callbacks);

    while (true) {
        uint32_t size = 0;
        if (!read_exact(&size, 4)) {
            break;
        }
        if (size == 0) {
            break;
        }
        if (size > 1000000u) {
            write_error("text is too long");
            break;
        }
        std::string text(size, '\0');
        if (!read_exact(&text[0], size)) {
            break;
        }
        std::string error;
        bool ok = synthesize_line(text, vcn, language, error);
        if (!ok) {
            write_error(error);
            continue;
        }
        std::vector<char> pcm;
        {
            std::lock_guard<std::mutex> lock(g_mu);
            pcm.swap(g_audio);
        }
        write_pcm(pcm);
    }

    AIKIT_UnInit();
    return 0;
}
