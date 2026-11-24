include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-tr3000-lite
PKG_RELEASE:=1
PKG_LICENSE:=MIT

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-tr3000-lite
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=TR3000 Lite Industrial LAN
  DEPENDS:=+luci-base +rpcd-mod-file
endef

define Package/luci-app-tr3000-lite/description
  Industrial LAN address and access controls through the fixed Lite controller.
endef

define Build/Compile
endef

define Package/luci-app-tr3000-lite/install
	$(INSTALL_DIR) $(1)/www
	$(CP) ./htdocs/* $(1)/www/
	$(CP) ./root/* $(1)/
endef

$(eval $(call BuildPackage,luci-app-tr3000-lite))
