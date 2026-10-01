import { registerPlugin } from "@capacitor/core";


const BackNavigation = registerPlugin("BackNavigation");


export async function subscribeAppBack(onBack, plugin = BackNavigation) {
  const handle = await plugin.addListener("backButton", onBack);
  return () => handle.remove();
}


export async function subscribeAppResume(onResume, plugin = BackNavigation) {
  const handle = await plugin.addListener("appResumed", onResume);
  return () => handle.remove();
}


export async function exitNativeApp(plugin = BackNavigation) {
  await plugin.exitApp();
}
