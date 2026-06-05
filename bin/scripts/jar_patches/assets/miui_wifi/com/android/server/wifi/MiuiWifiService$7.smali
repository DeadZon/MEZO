.class Lcom/android/server/wifi/MiuiWifiService$7;
.super Landroid/database/ContentObserver;


# annotations
.annotation system Ldalvik/annotation/EnclosingMethod;
    value = Lcom/android/server/wifi/MiuiWifiService;->registerCountryCodeChangedObserver()V
.end annotation

.annotation system Ldalvik/annotation/InnerClass;
    accessFlags = 0x0
    name = null
.end annotation


# instance fields
.field final synthetic this$0:Lcom/android/server/wifi/MiuiWifiService;


# direct methods
.method constructor <init>(Lcom/android/server/wifi/MiuiWifiService;Landroid/os/Handler;)V
    .registers 3

    iput-object p1, p0, Lcom/android/server/wifi/MiuiWifiService$7;->this$0:Lcom/android/server/wifi/MiuiWifiService;

    invoke-direct {p0, p2}, Landroid/database/ContentObserver;-><init>(Landroid/os/Handler;)V

    return-void
.end method


# virtual methods
.method public onChange(Z)V
    .registers 5

    invoke-static {}, Lcom/android/server/wifi/WifiInjector;->getInstance()Lcom/android/server/wifi/WifiInjector;

    move-result-object v0

    invoke-virtual {v0}, Lcom/android/server/wifi/WifiInjector;->getWifiCountryCode()Lcom/android/server/wifi/WifiCountryCode;

    move-result-object v0

    iget-object v1, p0, Lcom/android/server/wifi/MiuiWifiService$7;->this$0:Lcom/android/server/wifi/MiuiWifiService;

    invoke-static {v1}, Lcom/android/server/wifi/MiuiWifiService;->-$$Nest$fgetmContext(Lcom/android/server/wifi/MiuiWifiService;)Landroid/content/Context;

    move-result-object v1

    invoke-virtual {v1}, Landroid/content/Context;->getContentResolver()Landroid/content/ContentResolver;

    move-result-object v1

    const-string v2, "wifi_country_code"

    invoke-static {v1, v2}, Landroid/provider/Settings$Global;->getString(Landroid/content/ContentResolver;Ljava/lang/String;)Ljava/lang/String;

    move-result-object v1

    invoke-static {v1}, Landroid/text/TextUtils;->isEmpty(Ljava/lang/CharSequence;)Z

    move-result v2

    if-nez v2, :cond_0

    invoke-virtual {v0, v1}, Lcom/android/server/wifi/WifiCountryCode;->setOverrideCountryCode(Ljava/lang/String;)V

    goto :goto_0

    :cond_0
    invoke-virtual {v0}, Lcom/android/server/wifi/WifiCountryCode;->clearOverrideCountryCode()V

    :goto_0
    return-void
.end method
