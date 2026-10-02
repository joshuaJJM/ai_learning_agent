import XCTest

final class HaoXueUITests: XCTestCase {
    @MainActor
    func testDevelopmentPlaceholderLoadsMock() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.staticTexts["Mock Data Ready"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["好学"].exists)
        XCTAssertTrue(app.staticTexts["Development Build"].exists)
    }
}
