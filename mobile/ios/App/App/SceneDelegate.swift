import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = TrailMapViewController()
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

/// The web app (Trail Map, loaded from the server in capacitor.config.json) plus the app's own native plugins.
class TrailMapViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(OpenInPlugin())
    }
}

/// « Envoyer à ma montre »: iOS's « Ouvrir dans… » menu on the GPX, the one the Files app shows, where the
/// watch apps (COROS, Garmin Connect, Suunto…) are listed. A web page can't show it: that is why this app exists.
/// JS: Capacitor.nativePromise("OpenIn", "open", { filename: "x.gpx", data: "<base64>" }) -> { shown }
@objc(OpenInPlugin)
public class OpenInPlugin: CAPPlugin, CAPBridgedPlugin, UIDocumentInteractionControllerDelegate {
    public let identifier = "OpenInPlugin"
    public let jsName = "OpenIn"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "open", returnType: CAPPluginReturnPromise)
    ]

    // Kept alive while its menu is on screen (it is not retained by UIKit).
    private var controller: UIDocumentInteractionController?

    @objc func open(_ call: CAPPluginCall) {
        guard let name = call.getString("filename"),
              let base64 = call.getString("data"),
              let data = Data(base64Encoded: base64) else {
            call.reject("filename et data (base64) requis")
            return
        }
        // Only a file name, never a path from the page.
        let filename = (name as NSString).lastPathComponent.isEmpty ? "trail-map.gpx" : (name as NSString).lastPathComponent
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("gpx", isDirectory: true)
        let url = folder.appendingPathComponent(filename)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
        } catch {
            call.reject("impossible d'écrire le fichier", nil, error)
            return
        }
        DispatchQueue.main.async {
            guard let view = self.bridge?.viewController?.view else {
                call.reject("vue indisponible")
                return
            }
            let controller = UIDocumentInteractionController(url: url)
            controller.uti = "com.topografix.gpx"
            controller.name = filename
            controller.delegate = self
            self.controller = controller
            // Anchor (used on iPad): the bottom middle of the screen.
            let anchor = CGRect(x: view.bounds.midX, y: view.bounds.maxY - 80, width: 1, height: 1)
            // The apps that open the file first; else the full menu (Enregistrer dans Fichiers, AirDrop…).
            let shown = controller.presentOpenInMenu(from: anchor, in: view, animated: true)
                || controller.presentOptionsMenu(from: anchor, in: view, animated: true)
            call.resolve(["shown": shown])
        }
    }

    public func documentInteractionControllerDidDismissOpenInMenu(_ controller: UIDocumentInteractionController) {
        self.controller = nil
    }

    public func documentInteractionControllerDidDismissOptionsMenu(_ controller: UIDocumentInteractionController) {
        self.controller = nil
    }
}
