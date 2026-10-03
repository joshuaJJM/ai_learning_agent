import XCTest

final class SettingsUITests: XCTestCase {
    @MainActor
    func testSettingsPagesAndLocalPlan() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["设置"].tap()
        XCTAssertTrue(app.navigationBars["设置"].exists)

        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "好学计划")).firstMatch.tap()
        XCTAssertTrue(app.navigationBars["好学计划"].exists)
        app.buttons["模拟加入好学计划"].tap()
        XCTAssertTrue(app.staticTexts["已加入好学计划"].waitForExistence(timeout: 5))
        app.navigationBars.buttons["设置"].tap()

        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "学习额度")).firstMatch.tap()
        XCTAssertTrue(app.navigationBars["学习额度"].exists)
        XCTAssertTrue(app.staticTexts["20,000,000"].exists)
        app.navigationBars.buttons["设置"].tap()

        app.buttons["邀请同学"].tap()
        XCTAssertTrue(app.staticTexts["HAOXUE-7K3F"].exists)
        app.buttons["复制邀请码"].tap()
        XCTAssertTrue(app.buttons["已复制"].exists)
        app.navigationBars.buttons["设置"].tap()

        app.buttons["数据与隐私"].tap()
        XCTAssertTrue(app.navigationBars["数据与隐私"].exists)
        app.navigationBars.buttons["设置"].tap()
        app.buttons["专注模式"].tap()
        XCTAssertTrue(app.staticTexts["Hackathon Preview"].exists)
        app.navigationBars.buttons["设置"].tap()
        app.buttons["About 好学"].tap()
        XCTAssertTrue(app.staticTexts["Personal Learning Agent"].exists)
    }

    @MainActor
    func testBookSerialValidationAndUnlock() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["设置"].tap()
        app.buttons["图书与题库"].tap()
        XCTAssertTrue(app.navigationBars["图书与题库"].waitForExistence(timeout: 5))
        let firstBook = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "道练习")).firstMatch
        XCTAssertTrue(firstBook.waitForExistence(timeout: 10))
        firstBook.tap()
        XCTAssertTrue(app.navigationBars["图书详情"].exists)
        app.swipeUp()
        let unlock = app.buttons["检查并解锁"]
        XCTAssertTrue(unlock.waitForExistence(timeout: 5))
        unlock.tap()
        XCTAssertTrue(app.staticTexts["请输入图书序列号"].exists)
        let field = app.textFields["输入图书序列号"]
        field.tap()
        field.typeText("114514")
        app.buttons["检查并解锁"].tap()
        XCTAssertTrue(app.alerts["序列号有效"].waitForExistence(timeout: 5))
        app.alerts.buttons["稍后"].tap()
        XCTAssertTrue(app.staticTexts["已加入你的题库"].exists)
    }
}
