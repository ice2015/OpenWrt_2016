include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-tr3000-full
PKG_RELEASE:=1
PKG_LICENSE:=MIT

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-tr3000-full
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=TR3000 Full service controls
  DEPENDS:=+luci-base +rpcd-mod-file
endef

define Package/luci-app-tr3000-full/description
  Standard LuCI page for fixed TR3000 Full remote-service controls.
endef

define Build/Compile
endef

define Package/luci-app-tr3000-full/install
	$(INSTALL_DIR) $(1)/www
	$(CP) ./htdocs/* $(1)/www/
	$(CP) ./root/* $(1)/
endef

$(eval $(call BuildPackage,luci-app-tr3000-full))
