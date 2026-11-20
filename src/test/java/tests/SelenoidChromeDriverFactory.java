package tests;

import com.codeborne.selenide.Browser;
import com.codeborne.selenide.Config;
import com.codeborne.selenide.webdriver.ChromeDriverFactory;
import org.openqa.selenium.Proxy;
import org.openqa.selenium.UsernameAndPassword;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.remote.RemoteWebDriver;

import java.io.File;

public class SelenoidChromeDriverFactory extends ChromeDriverFactory {
    @Override
    public WebDriver create(Config config, Browser browser, Proxy proxy, File downloadsFolder) {
        var credentials = new UsernameAndPassword(required("SELENOID_USERNAME"), required("SELENOID_PASSWORD"));
        return RemoteWebDriver.builder()
                .address("https://selenoid.qa.guru/wd/hub")
                .authenticateAs(credentials)
                .oneOf(createCapabilities(config, browser, proxy, null))
                .build();
    }

    private static String required(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalStateException("Missing Selenoid credential: " + name);
        }
        return value;
    }
}
