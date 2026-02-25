# Overview

`my_company.my_cpp_extension` 은 Omniverse Kit 에서 동작하는 **C++ 네이티브 플러그인 예제**입니다.  
이 확장은 Kit 의 전역 업데이트 이벤트를 구독해서 **약 10초마다 로그를 출력**하는 아주 단순한 동작을 합니다.

아래 내용은 `plugins/my_company.my_cpp_extension/CppExtension.cpp` 구현을 기준으로 설명합니다.

---

## 1. 플러그인 메타데이터와 의존성

```cpp
```35:45:source/extensions/my_company.my_cpp_extension/plugins/my_company.my_cpp_extension/CppExtension.cpp
const struct carb::PluginImplDesc kPluginImpl = {
    EXTENSION_NAME,
    "Example of a native plugin extension.",
    "NVIDIA",
    carb::PluginHotReload::eDisabled,
    "dev"
};

CARB_PLUGIN_IMPL_DEPS(omni::kit::IApp, carb::logging::ILogging)
```

- `PluginImplDesc` 에 플러그인 이름, 설명, 작성자, 버전 등을 등록합니다.
- `CARB_PLUGIN_IMPL_DEPS` 로 이 플러그인이 **Kit 앱(`omni::kit::IApp`)** 과 **로깅(`carb::logging::ILogging`)** 을 필요로 한다고 선언합니다.
  - 이렇게 해야 Carbonite 가 플러그인을 로드할 때 필요한 인터페이스를 올바르게 연결할 수 있습니다.

---

## 2. 확장 클래스 구조 (`NativeExtensionExample`)

```cpp
```48:81:source/extensions/my_company.my_cpp_extension/plugins/my_company.my_cpp_extension/CppExtension.cpp
class NativeExtensionExample : public omni::ext::IExt
{
public:
    void onStartup(const char* extId) override;
    void onShutdown() override;

private:
    int m_counter = 0;
    int m_last_print_counter = 0;
    carb::eventdispatcher::ObserverGuard m_subscription;
};
```

- `omni::ext::IExt` 를 상속한 C++ 클래스가 **확장의 수명주기** 를 담당합니다.
  - `onStartup` 에서 이벤트 구독 및 초기화 수행
  - `onShutdown` 에서 리소스 정리 (이벤트 구독 해제 등)
- 멤버 변수 의미:
  - `m_counter`  
    업데이트 콜백이 호출된 **총 횟수(프레임 수)** 를 누적하는 카운터
  - `m_last_print_counter`  
    마지막으로 로그를 찍었을 때의 `m_counter` 값 (10초 간격 계산에 사용)
  - `m_subscription`  
    이벤트 구독 핸들을 RAII 방식으로 관리하는 객체

---

## 3. 전역 업데이트 이벤트 구독과 10초 주기 로그

```cpp
```51:68:source/extensions/my_company.my_cpp_extension/plugins/my_company.my_cpp_extension/CppExtension.cpp
void onStartup(const char* extId) override
{
    printf(EXTENSION_NAME ": in onStartup\n");

    auto ed = carb::getCachedInterface<carb::eventdispatcher::IEventDispatcher>();
    m_subscription = ed->observeEvent(
        carb::RStringKey("cpp.example.update"),
        0,
        omni::kit::kGlobalEventUpdate,
        [this](const carb::eventdispatcher::Event& e) {
            m_counter++;
            if (m_counter - m_last_print_counter >= kUpdatesPer10Seconds)
            {
                printf(EXTENSION_NAME ": %d (every 10s)\n", m_counter);
                CARB_LOG_INFO(EXTENSION_NAME ": %d (every 10s)\n", m_counter);
                m_last_print_counter = m_counter;
            }
        });
}
```

- `carb::getCachedInterface<IEventDispatcher>()`  
  Carbonite 전역에서 **이벤트 디스패처 인터페이스**를 가져옵니다.
- `observeEvent(...)` 로 전역 업데이트 스트림에 구독을 등록합니다.
  - 채널 키: `"cpp.example.update"`
  - 이벤트 타입: `omni::kit::kGlobalEventUpdate` (주로 매 프레임 호출되는 업데이트 이벤트)
  - 콜백 람다:
    - 호출될 때마다 `m_counter` 를 1씩 증가
    - 마지막 로그 시점과의 차이 `m_counter - m_last_print_counter` 가
      `kUpdatesPer10Seconds`(기본 600) 이상일 때만 로그 출력
    - 출력 후 `m_last_print_counter` 를 현재 값으로 갱신 → 다음 10초를 위한 기준점

이렇게 해서 **정확한 시간 단위 대신 “업데이트 호출 횟수”를 이용해 약 10초 간격을 구현**합니다.  
프레임레이트가 달라지면 `kUpdatesPer10Seconds` 값을 조정하면 됩니다.

---

## 4. 종료 시 이벤트 구독 해제

```cpp
```71:75:source/extensions/my_company.my_cpp_extension/plugins/my_company.my_cpp_extension/CppExtension.cpp
void onShutdown() override
{
    // Unsubscribes from the event stream
    m_subscription.reset();
}
```

- 확장이 언로드될 때 `m_subscription.reset()` 을 호출해 **이벤트 구독을 해제**합니다.
- 이를 잊으면:
  - 확장 객체가 파괴된 뒤에도 콜백이 호출될 수 있고,
  - 그 결과 크래시나 정의되지 않은 동작이 발생할 수 있으므로 반드시 정리가 필요합니다.

---

## 5. 플러그인 등록 매크로

```cpp
```84:90:source/extensions/my_company.my_cpp_extension/plugins/my_company.my_cpp_extension/CppExtension.cpp
// Generate boilerplate code
CARB_PLUGIN_IMPL(kPluginImpl, NativeExtensionExample)

void fillInterface(NativeExtensionExample& iface)
{
}
```

- `CARB_PLUGIN_IMPL(kPluginImpl, NativeExtensionExample)`  
  - Carbonite 에게 “이 플러그인은 `kPluginImpl` 메타데이터를 가지며,  
    구현 클래스는 `NativeExtensionExample` 이다” 라고 등록합니다.
  - 내부적으로 플러그인 진입점 코드(등록/시작/중지)를 생성합니다.
- `fillInterface`  
  - 이 플러그인이 `NativeExtensionExample` 타입 인터페이스를 외부에 노출하려 할 때 사용될 수 있는 후크입니다.
  - 현재는 특별한 초기화가 필요하지 않아서 빈 구현으로 남겨 둔 상태입니다.