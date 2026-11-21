#pragma once

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <memory>
#include <nlohmann/json.hpp>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace HcodeRMapPermit {
inline constexpr std::string_view StockMap = "/levels/west_coast_usa/info.json";
inline constexpr std::string_view MapFlag = "?hcoderMapPermit=";

inline bool IsHex256(const std::string& value) {
    return value.size() == 64 && value.find_first_not_of("0123456789abcdef") == std::string::npos;
}

inline std::string Base64Url(const unsigned char* bytes, size_t size) {
    std::string output(4 * ((size + 2) / 3) + 1, '\0');
    const int length = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(output.data()), bytes, int(size));
    if (length <= 0) {
        throw std::runtime_error("map permit encoding");
    }
    output.resize(length);
    std::replace(output.begin(), output.end(), '+', '-');
    std::replace(output.begin(), output.end(), '/', '_');
    while (output.back() == '=') {
        output.pop_back();
    }
    return output;
}

inline std::string RandomId() {
    std::array<unsigned char, 16> entropy {};
    if (RAND_bytes(entropy.data(), int(entropy.size())) != 1) {
        throw std::runtime_error("map permit RNG");
    }
    std::string result;
    constexpr char Hex[] = "0123456789abcdef";
    for (auto byte : entropy) {
        result += Hex[byte >> 4];
        result += Hex[byte & 15];
    }
    return result;
}

inline std::string BuildMapRequest(
    const std::string& configuredMap,
    const std::filesystem::path& releasePath = "/run/secrets/hcoder-map-release.json",
    const std::filesystem::path& signingPath = "/run/secrets/signing-private.pem") {
    if (configuredMap != StockMap || !std::filesystem::exists(releasePath)) {
        return configuredMap;
    }
    if (!std::filesystem::is_regular_file(releasePath) || std::filesystem::file_size(releasePath) > 4096) {
        throw std::runtime_error("map permit descriptor");
    }
    std::ifstream file(releasePath, std::ios::binary);
    const auto release = nlohmann::json::parse(file, nullptr, false);
    if (!release.is_object() || release.value("version", 0) != 1) {
        throw std::runtime_error("map permit descriptor");
    }

    const auto sha = release.value("archiveSha256", std::string {});
    const auto manifest = release.value("manifestSha256", std::string {});
    const auto secret = release.value("contentKey", std::string {});
    const auto hosts = release.value("hosts", std::vector<std::string> {});
    const int port = release.value("port", 0);
    if (!IsHex256(sha) || !IsHex256(manifest) || !IsHex256(secret)
        || hosts.empty() || hosts.size() > 4 || port < 1 || port > 65535) {
        throw std::runtime_error("map permit claims");
    }
    for (const auto& host : hosts) {
        if (host.empty() || host.size() > 60
            || host.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789.-") != std::string::npos) {
            throw std::runtime_error("map permit host");
        }
    }

    const auto now = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    const auto payload = nlohmann::json {
        {"v", 1}, {"kid", "mg-rsa-2026-01"}, {"mod", "hcoder-map"},
        {"sha", sha}, {"manifest", manifest}, {"key", secret},
        {"hosts", hosts}, {"port", port}, {"jti", RandomId()}, {"iat", now}, {"exp", now + 180}
    }.dump();
    const auto wirePayload = Base64Url(reinterpret_cast<const unsigned char*>(payload.data()), payload.size());

    const std::unique_ptr<BIO, decltype(&BIO_free)> pem(BIO_new_file(signingPath.string().c_str(), "r"), BIO_free);
    const std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> signer(
        pem ? PEM_read_bio_PrivateKey(pem.get(), nullptr, nullptr, nullptr) : nullptr, EVP_PKEY_free);
    const std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> ctx(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!signer || !ctx || EVP_PKEY_base_id(signer.get()) != EVP_PKEY_RSA || EVP_PKEY_bits(signer.get()) != 2048
        || EVP_DigestSignInit(ctx.get(), nullptr, EVP_sha256(), nullptr, signer.get()) != 1
        || EVP_DigestSignUpdate(ctx.get(), wirePayload.data(), wirePayload.size()) != 1) {
        throw std::runtime_error("map permit signature initialization");
    }
    size_t length = 0;
    if (EVP_DigestSignFinal(ctx.get(), nullptr, &length) != 1 || length != 256) {
        throw std::runtime_error("map permit signature length");
    }
    std::array<unsigned char, 256> signature {};
    if (EVP_DigestSignFinal(ctx.get(), signature.data(), &length) != 1 || length != signature.size()) {
        throw std::runtime_error("map permit signature");
    }
    return configuredMap + std::string(MapFlag) + wirePayload + '.' + Base64Url(signature.data(), length);
}
}
