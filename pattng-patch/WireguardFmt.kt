package com.v2ray.ang.fmt

import com.v2ray.ang.AppConfig
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.extension.idnHost
import com.v2ray.ang.extension.nullIfBlank
import com.v2ray.ang.extension.removeWhiteSpace
import com.v2ray.ang.util.JsonUtil
import com.v2ray.ang.util.Utils
import java.net.URI

object WireguardFmt : FmtBase() {
    /**
     * Parses a URI string into a ProfileItem object.
     *
     * @param str the URI string to parse
     * @return the parsed ProfileItem object, or null if parsing fails
     */
    fun parse(str: String): ProfileItem? {
        val config = ProfileItem.create(EConfigType.WIREGUARD)

        val uri = URI(Utils.fixIllegalUrl(str))
        if (uri.rawQuery.isNullOrEmpty()) return null
        val queryParam = getQueryParam(uri)

        // Happ may put extras after the fragment: "BS DE?serverDescription=..."
        val fragment = Utils.decodeURIComponent(uri.fragment.orEmpty())
        config.remarks = fragment.substringBefore("?").ifEmpty { "none" }
        config.server = uri.idnHost
        config.serverPort = uri.port.toString()

        config.secretKey = Utils.decodeURIComponent(uri.userInfo.orEmpty())
        config.localAddress = queryParam["address"] ?: AppConfig.WIREGUARD_LOCAL_ADDRESS_V4
        config.publicKey = queryParam["publickey"] ?: queryParam["publicKey"].orEmpty()
        config.preSharedKey = queryParam["presharedkey"]?.nullIfBlank()
        config.mtu = Utils.parseInt(queryParam["mtu"] ?: AppConfig.WIREGUARD_LOCAL_MTU)
        config.reserved = queryParam["reserved"] ?: "0,0,0"
        config.finalMask = queryParam["fm"]?.nullIfBlank()
            ?: buildFinalMaskFromAmnezia(
                i1 = queryParam["i1"] ?: queryParam["I1"],
                jc = queryParam["jc"] ?: queryParam["Jc"],
                jmin = queryParam["jmin"] ?: queryParam["Jmin"],
                jmax = queryParam["jmax"] ?: queryParam["Jmax"],
            )

        return config
    }

    /**
     * Parses a Wireguard / AmneziaWG configuration file string into a ProfileItem object.
     *
     * @param str the Wireguard configuration file string to parse
     * @return the parsed ProfileItem object, or null if parsing fails
     */
    fun parseWireguardConfFile(str: String): ProfileItem {
        val config = ProfileItem.create(EConfigType.WIREGUARD)

        val interfaceParams: MutableMap<String, String> = mutableMapOf()
        val peerParams: MutableMap<String, String> = mutableMapOf()

        var currentSection: String? = null

        str.lines().forEach { line ->
            val trimmedLine = line.trim()

            if (trimmedLine.isEmpty() || trimmedLine.startsWith("#")) {
                return@forEach
            }

            when {
                trimmedLine.startsWith("[Interface]", ignoreCase = true) -> currentSection = "Interface"
                trimmedLine.startsWith("[Peer]", ignoreCase = true) -> currentSection = "Peer"
                else -> {
                    if (currentSection != null) {
                        val parts = trimmedLine.split("=", limit = 2).map { it.trim() }
                        if (parts.size == 2) {
                            val key = parts[0].lowercase()
                            val value = parts[1]
                            when (currentSection) {
                                "Interface" -> interfaceParams[key] = value
                                "Peer" -> peerParams[key] = value
                            }
                        }
                    }
                }
            }
        }

        config.secretKey = interfaceParams["privatekey"].orEmpty()
        config.remarks = System.currentTimeMillis().toString()
        config.localAddress = interfaceParams["address"] ?: AppConfig.WIREGUARD_LOCAL_ADDRESS_V4
        config.mtu = Utils.parseInt(interfaceParams["mtu"] ?: AppConfig.WIREGUARD_LOCAL_MTU)
        config.publicKey = peerParams["publickey"].orEmpty()
        config.preSharedKey = peerParams["presharedkey"]?.nullIfBlank()
        val endpoint = peerParams["endpoint"].orEmpty()
        val endpointParts = endpoint.split(":", limit = 2)
        if (endpointParts.size == 2) {
            config.server = endpointParts[0]
            config.serverPort = endpointParts[1]
        } else {
            config.server = endpoint
            config.serverPort = ""
        }
        config.reserved = peerParams["reserved"] ?: "0,0,0"
        config.finalMask = buildFinalMaskFromAmnezia(
            i1 = interfaceParams["i1"],
            jc = interfaceParams["jc"],
            jmin = interfaceParams["jmin"],
            jmax = interfaceParams["jmax"],
        )

        return config
    }

    /**
     * Map AmneziaWG I1 / Jc junk into Xray Finalmask UDP noise JSON.
     * Stock PattNG applies profileItem.finalMask onto WireGuard outbounds.
     */
    fun buildFinalMaskFromAmnezia(
        i1: String?,
        jc: String?,
        jmin: String?,
        jmax: String?,
    ): String? {
        val noises = mutableListOf<Map<String, Any>>()
        val i1Hex = i1ToHex(i1)
        if (!i1Hex.isNullOrEmpty()) {
            noises.add(
                mapOf(
                    "type" to "hex",
                    "packet" to i1Hex,
                    "delay" to "0",
                )
            )
        }
        val junkCount = jc?.toIntOrNull()?.coerceIn(0, 10) ?: 0
        val size = "${(jmin?.trim().nullIfBlank() ?: "40")}-${(jmax?.trim().nullIfBlank() ?: "70")}"
        repeat(junkCount) {
            noises.add(
                mapOf(
                    "rand" to size,
                    "delay" to "0-5",
                )
            )
        }
        if (noises.isEmpty()) return null
        val finalMask = mapOf(
            "udp" to listOf(
                mapOf(
                    "type" to "noise",
                    "settings" to mapOf(
                        "reset" to "25-60",
                        "noise" to noises,
                    ),
                )
            )
        )
        return JsonUtil.toJson(finalMask)
    }

    private fun i1ToHex(i1: String?): String? {
        val text = i1?.trim().orEmpty()
        if (text.isEmpty()) return null
        val tagged = Regex("""<b\s+0x([0-9a-fA-F]+)>""").find(text)
        if (tagged != null) return tagged.groupValues[1].lowercase()
        if (text.matches(Regex("^[0-9a-fA-F]+$")) && text.length % 2 == 0) {
            return text.lowercase()
        }
        return null
    }

    /**
     * Converts a ProfileItem object to a URI string.
     *
     * @param config the ProfileItem object to convert
     * @return the converted URI string
     */
    fun toUri(config: ProfileItem): String {
        val dicQuery = HashMap<String, String>()

        dicQuery["publickey"] = config.publicKey.orEmpty()
        if (config.reserved != null) {
            dicQuery["reserved"] = config.reserved.removeWhiteSpace().orEmpty()
        }
        dicQuery["address"] = config.localAddress.removeWhiteSpace().orEmpty()
        if (config.mtu != null) {
            dicQuery["mtu"] = config.mtu.toString()
        }
        if (config.preSharedKey != null) {
            dicQuery["presharedkey"] = config.preSharedKey.removeWhiteSpace().orEmpty()
        }
        config.finalMask?.nullIfBlank()?.let { dicQuery["fm"] = it }

        return toUri(config, config.secretKey, dicQuery)
    }
}
