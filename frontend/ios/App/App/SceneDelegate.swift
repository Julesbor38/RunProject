import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = RunProjectViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }
}

/// The web app plus this app's own native plugin.
class RunProjectViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(OpenWithPlugin())
    }
}

/// « Envoyer à ma montre »: iOS's « Ouvrir avec… » menu on the GPX file, the one the Files app shows, which lists
/// the apps that open GPX files (COROS, Garmin Connect, Suunto…). The share sheet may not list them.
/// JS: registerPlugin("OpenWith").open({ url: "file://…/x.gpx" }) -> { shown: Bool } (false: no app opens it).
@objc(OpenWithPlugin)
public class OpenWithPlugin: CAPPlugin, CAPBridgedPlugin, UIDocumentInteractionControllerDelegate {
    public let identifier = "OpenWithPlugin"
    public let jsName = "OpenWith"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "open", returnType: CAPPluginReturnPromise)
    ]

    // Kept while its menu is on screen (UIKit does not retain it).
    private var controller: UIDocumentInteractionController?

    @objc func open(_ call: CAPPluginCall) {
        guard let raw = call.getString("url"), let url = URL(string: raw), url.isFileURL,
              FileManager.default.fileExists(atPath: url.path) else {
            call.reject("fichier introuvable")
            return
        }
        DispatchQueue.main.async {
            guard let view = self.bridge?.viewController?.view else {
                call.reject("vue indisponible")
                return
            }
            let controller = UIDocumentInteractionController(url: url)
            controller.delegate = self
            self.controller = controller
            let anchor = CGRect(x: view.bounds.midX, y: view.bounds.maxY - 80, width: 1, height: 1) // iPad
            let shown = controller.presentOpenInMenu(from: anchor, in: view, animated: true)
            if !shown { self.controller = nil }
            call.resolve(["shown": shown])
        }
    }

    public func documentInteractionControllerDidDismissOpenInMenu(_ controller: UIDocumentInteractionController) {
        self.controller = nil
    }
}
