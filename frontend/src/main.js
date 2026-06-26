import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import "vis-network/styles/vis-network.css";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
import { createPinia } from "pinia";
import TDesignChat from "@tdesign-vue-next/chat";

import App from "./App.vue";
import router from "./router";

const app = createApp(App);

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

app.use(ElementPlus);
app.use(TDesignChat);
const pinia = createPinia();
app.use(pinia);
app.use(router);

app.mount("#app");
